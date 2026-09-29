from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import case, inspect, select, text
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.deps import CsrfUser, CurrentUser, Db, require_class, require_team
from app.core.errors import ApiError
from app.core.utils import now
from app.database import SessionLocal, engine
from app.models import AiChatMessage, Assignment, SubmissionDocument, SubmissionWorkspace, TeachingClass
from app.modules.ai_teacher.client import AiClientError, get_ai_client
from app.modules.ai_teacher.retrieval import html_to_text, normalize_reference_text, normalize_text, refresh_assignment_ai_chunks, retrieve_contexts, retrieve_subject_contexts
from app.modules.ai_teacher.answer_policy import SELF_CHECK_GUIDANCE, asks_for_answer_review, guarded_answer
from app.modules.ai_teacher.service import build_messages, clearly_off_topic
from app.modules.ai_teacher.streaming import batch_deltas
from app.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)
_active_students: set[UUID] = set()
_active_lock = Lock()


class AiTeacherChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID
    quote: str = ""
    quote_source: Literal["workspace", "assignment"] | None = None
    message_id: UUID | None = None


def check_schema(db: Db) -> None:
    schema = inspect(db.get_bind())
    tables = set(schema.get_table_names())
    required = {"ai_teacher_chat_messages", "ai_teacher_knowledge_chunks", "ai_teacher_subject_knowledge", "ai_teacher_knowledge_nodes"}
    if not required.issubset(tables):
        raise ApiError(503, "AI_TEACHER_SCHEMA_MISSING", "AI 老师数据表尚未就绪，请运行数据库迁移")
    if "conversation_id" not in {item["name"] for item in schema.get_columns("ai_teacher_chat_messages")} or not {"embedding", "metadata"}.issubset({item["name"] for item in schema.get_columns("ai_teacher_knowledge_chunks")}):
        raise ApiError(503, "AI_TEACHER_SCHEMA_MISSING", "AI 老师数据表尚未就绪，请运行数据库迁移")


def reserve_student(student_id: UUID) -> None:
    with _active_lock:
        if student_id in _active_students or len(_active_students) >= settings.ai_teacher_max_concurrent_per_worker:
            raise ApiError(429, "AI_TEACHER_BUSY", "叶老师正在回答其他问题，请稍后重试")
        _active_students.add(student_id)


def release_student(student_id: UUID) -> None:
    with _active_lock:
        _active_students.discard(student_id)


def lock_student_across_workers(student_id: UUID):
    connection = engine.connect()
    resource = f"ai-teacher-student-{student_id}"
    try:
        result = connection.scalar(text(
            "DECLARE @result int; EXEC @result = sp_getapplock "
            "@Resource=:resource, @LockMode='Exclusive', @LockOwner='Session', @LockTimeout=0; SELECT @result"
        ), {"resource": resource})
        if result is None or result < 0:
            raise ApiError(429, "AI_TEACHER_BUSY", "你已有一条问题正在回答，请稍后重试")
        return connection, resource
    except Exception:
        connection.close()
        raise


def unlock_student_across_workers(connection, resource: str) -> None:
    try:
        connection.execute(text("EXEC sp_releaseapplock @Resource=:resource, @LockOwner='Session'"), {"resource": resource})
    finally:
        connection.close()


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def ai_message_json(item: AiChatMessage) -> dict:
    return {
        "id": str(item.id),
        "role": item.role,
        "conversation_id": str(item.conversation_id),
        "content": item.content,
        "contexts": item.contexts or [],
        "created_at": item.created_at.isoformat(),
    }


def accessible_assignment(db: Db, user: CurrentUser, aid: UUID) -> Assignment:
    assignment = db.get(Assignment, aid)
    if not assignment:
        raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    if user.role == "STUDENT":
        if assignment.status not in {"PUBLISHED", "CLOSED"}:
            raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
        if assignment.starts_at and assignment.starts_at > now():
            raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    return assignment


def workspace_scope(db: Db, assignment: Assignment, user: CurrentUser) -> tuple[UUID | None, UUID | None, SubmissionWorkspace | None]:
    if user.role != "STUDENT":
        return None, None, None
    owner_user_id = user.id if assignment.submitter_type == "INDIVIDUAL" else None
    owner_team_id = None
    if assignment.submitter_type == "TEAM":
        _, team = require_team(db, assignment.class_id, user)
        owner_team_id = team.id
    workspace = db.scalar(
        select(SubmissionWorkspace).where(
            SubmissionWorkspace.assignment_id == assignment.id,
            SubmissionWorkspace.owner_user_id == owner_user_id,
            SubmissionWorkspace.owner_team_id == owner_team_id,
        )
    )
    return owner_user_id, owner_team_id, workspace


@router.get("/api/v1/assignments/{aid}/ai-teacher/history")
def ai_teacher_history(aid: UUID, conversation_id: UUID, user: CurrentUser, db: Db):
    assignment = accessible_assignment(db, user, aid)
    if user.role != "STUDENT":
        raise ApiError(403, "STUDENT_REQUIRED", "仅学生可以使用 AI 老师")
    check_schema(db)
    rows = db.scalars(
        select(AiChatMessage)
        .where(AiChatMessage.assignment_id == assignment.id, AiChatMessage.student_id == user.id, AiChatMessage.conversation_id == conversation_id)
        .order_by(AiChatMessage.created_at, case((AiChatMessage.role == "user", 0), else_=1), AiChatMessage.id)
    ).all()
    return {"enabled": settings.ai_teacher_enabled, "messages": [ai_message_json(item) for item in rows]}


@router.post("/api/v1/assignments/{aid}/ai-teacher/chat")
async def chat_with_ai_teacher(aid: UUID, data: AiTeacherChatIn, request: Request, user: CsrfUser, db: Db):
    request_started = time.perf_counter()
    assignment = accessible_assignment(db, user, aid)
    if user.role != "STUDENT":
        raise ApiError(403, "STUDENT_REQUIRED", "仅学生可以使用 AI 老师")
    check_schema(db)
    question = data.question.strip()
    if not question:
        raise ApiError(422, "QUESTION_REQUIRED", "请填写问题")
    owner_user_id, owner_team_id, workspace = workspace_scope(db, assignment, user)
    quote = normalize_reference_text(data.quote)
    if data.quote_source and not quote:
        raise ApiError(422, "QUOTE_EMPTY", "引用内容为空，请重新选择文字")
    if len(quote) > settings.ai_teacher_max_quote_chars:
        raise ApiError(422, "QUOTE_TOO_LONG", "引用内容过长，请缩短选区")
    if quote:
        if data.quote_source == "workspace":
            if not workspace:
                raise ApiError(422, "QUOTE_OUT_OF_SCOPE", "当前没有可访问的作业工作区")
        else:
            sources = [normalize_text(html_to_text(assignment.description))]
            if data.quote_source is None and workspace:
                sources.extend(normalize_reference_text(item.markdown_content or "", markdown_source=True) for item in db.scalars(
                    select(SubmissionDocument).where(SubmissionDocument.workspace_id == workspace.id)
                ).all())
            if not any(quote in source for source in sources):
                raise ApiError(422, "QUOTE_OUT_OF_SCOPE", "引用内容不在当前作业中，请从作业要求或当前文档中重新选择")
    if clearly_off_topic(question):
        raise ApiError(422, "QUESTION_OFF_TOPIC", "叶老师只回答本课程和当前作业相关的问题")
    if not settings.ai_teacher_enabled:
        raise ApiError(503, "AI_TEACHER_DISABLED", "叶老师暂未启用")
    refresh_assignment_ai_chunks(db, assignment, workspace)
    db.flush()
    contexts = retrieve_contexts(db, assignment.id, question + " " + quote, owner_user_id, owner_team_id)
    course = db.get(TeachingClass, assignment.class_id)
    contexts += retrieve_subject_contexts(db, assignment.class_id, course.course, question)
    history = db.scalars(
        select(AiChatMessage)
        .where(AiChatMessage.assignment_id == assignment.id, AiChatMessage.student_id == user.id, AiChatMessage.conversation_id == data.conversation_id)
        .order_by(AiChatMessage.created_at.desc(), case((AiChatMessage.role == "assistant", 0), else_=1), AiChatMessage.id.desc())
        .limit(settings.ai_teacher_max_history)
    ).all()
    history = list(reversed(history))
    review_request = asks_for_answer_review(question)
    messages = build_messages(assignment, question, contexts, history, quote) if not review_request else []
    context_payload = [item.json() for item in contexts]
    db.rollback()  # Retrieved chunks are transient; do not write them for an interrupted stream.
    preparation_ms = round((time.perf_counter() - request_started) * 1000)
    reserve_student(user.id)
    try:
        lock_connection, lock_resource = lock_student_across_workers(user.id)
    except Exception:
        release_student(user.id)
        raise

    async def events():
        parts = []
        output_chars = 0
        deltas = None
        first_sse_ms = None
        try:
            async def fixed_guidance():
                yield SELF_CHECK_GUIDANCE

            source = fixed_guidance() if review_request else guarded_answer(get_ai_client().stream_chat(messages))
            deltas = batch_deltas(source)
            async for delta in deltas:
                if await request.is_disconnected():
                    return
                if output_chars + len(delta) > 6000:
                    raise AiClientError("回答超过长度限制，请缩小问题范围")
                parts.append(delta)
                output_chars += len(delta)
                if first_sse_ms is None:
                    first_sse_ms = round((time.perf_counter() - request_started) * 1000)
                yield sse("delta", {"text": delta})
            answer = "".join(parts).strip()
            if not answer:
                raise AiClientError("模型服务没有返回内容")
            if await request.is_disconnected():
                return
            with SessionLocal() as stream_db:
                question_time = now()
                user_message = AiChatMessage(id=data.message_id or uuid4(), assignment_id=aid, student_id=user.id, conversation_id=data.conversation_id, role="user", content=question, contexts=[{"quote": quote}] if quote else [], created_at=question_time)
                assistant_message = AiChatMessage(assignment_id=aid, student_id=user.id, conversation_id=data.conversation_id, role="assistant", content=answer, contexts=context_payload, created_at=question_time + timedelta(microseconds=1))
                stream_db.add_all([user_message, assistant_message])
                stream_db.flush()
                result = [ai_message_json(user_message), ai_message_json(assistant_message)]
                done_event = sse("done", {"messages": result})
                stream_db.commit()
            yield done_event
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield sse("error", {"message": str(exc) if isinstance(exc, AiClientError) else "叶老师暂时无法回答，请稍后重试"})
        finally:
            try:
                if deltas is not None:
                    await deltas.aclose()
            finally:
                logger.info(
                    "ai_teacher_chat preparation_ms=%s first_sse_ms=%s duration_ms=%s output_chars=%s",
                    preparation_ms, first_sse_ms, round((time.perf_counter() - request_started) * 1000), output_chars,
                )
                unlock_student_across_workers(lock_connection, lock_resource)
                release_student(user.id)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
