from __future__ import annotations

import asyncio, csv, html, io, json, mimetypes, os, re, secrets
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from decimal import Decimal
from pathlib import Path
from ipaddress import ip_address, ip_network
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import Cookie, Depends, FastAPI, File, Header, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
import bleach
import zipfile
from oss2.exceptions import NoSuchKey, OssError
import tempfile
from tempfile import TemporaryFile
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, load_only

from app.database import SessionLocal, get_db
from app.grading import final_score, finalize_campaign
from app.models import Assignment, AuditLog, BackgroundJob, ClassJoinRequest, ClassMember, FileObject, Grade, GradeCoefficient, GradeRevision, ImportBatch, LoginSession, Notification, PeerReview, ReviewAssignment, ReviewCampaign, RoleMenuPermission, Submission, SubmissionAnnotation, SubmissionAssessment, SubmissionDocument, SubmissionVersion, SubmissionWorkspace, TeachingClass, TeachingMaterial, TeachingMaterialFolder, Team, TeamMember, TeamRequest, Topic, User, VersionFile
from app.security import hash_password, new_session, token_hash, verify_password
from app.settings import settings
from app import storage
from app.realtime import hub as realtime_hub, publish_event

@asynccontextmanager
async def lifespan(_: FastAPI):
    await realtime_hub.start()
    try:
        yield
    finally:
        await realtime_hub.stop()


app = FastAPI(title="软件工程作业系统 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
request_client_id: ContextVar[str | None] = ContextVar("request_client_id", default=None)
request_ip_address: ContextVar[str | None] = ContextVar("request_ip_address", default=None)
request_trace_id: ContextVar[str | None] = ContextVar("request_trace_id", default=None)

SAFE_HTML_TAGS = ["div", "span", "section", "article", "header", "footer", "main", "p", "br", "h1", "h2", "h3", "h4", "strong", "b", "em", "s", "small", "u", "ul", "ol", "li", "blockquote", "pre", "code", "a", "table", "thead", "tbody", "tr", "th", "td", "img", "hr", "input"]
SAFE_HTML_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "input": ["type", "checked", "disabled"],
}
PREVIEWABLE_FILE_SUFFIXES = {".md"}
DOWNLOAD_ONLY_FILE_SUFFIXES = {".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".docx", ".pptx", ".xlsx", ".zip", ".rar", ".7z"}
STUDENT_UPLOAD_FILE_SUFFIXES = PREVIEWABLE_FILE_SUFFIXES | {".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
MENU_CATALOG = [
    {"key": "overview", "labels": {"TEACHER": "总览", "STUDENT": "总览"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "classes", "labels": {"TEACHER": "教学班"}, "roles": ["TEACHER"]},
    {"key": "teams", "labels": {"TEACHER": "小组与选题", "STUDENT": "我的小组"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "assignments", "labels": {"TEACHER": "作业管理", "STUDENT": "我的作业"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "reviews", "labels": {"STUDENT": "作品互评"}, "roles": ["STUDENT"]},
    {"key": "capstone", "labels": {"TEACHER": "大作业管理", "STUDENT": "大作业"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "materials", "labels": {"TEACHER": "教学资料", "STUDENT": "教学资料"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "grades", "labels": {"TEACHER": "成绩与导出", "STUDENT": "成绩与反馈"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "system", "labels": {"TEACHER": "系统与审计"}, "roles": ["TEACHER"]},
]


def menu_permissions_by_role(db: Session) -> dict[str, list[str]]:
    stored = {(item.role, item.menu_key): item.enabled for item in db.scalars(select(RoleMenuPermission)).all()}
    return {
        role: [item["key"] for item in MENU_CATALOG if role in item["roles"] and stored.get((role, item["key"]), True)]
        for role in ("TEACHER", "STUDENT")
    }


def menu_permissions_payload(db: Session, user: User) -> dict:
    roles = menu_permissions_by_role(db)
    payload = {"catalog": MENU_CATALOG, "enabled": roles[user.role], "can_manage": user.role == "TEACHER"}
    if user.role == "TEACHER": payload["roles"] = roles
    return payload


def clean_html(value: str) -> str:
    cleaned = bleach.clean(value, tags=SAFE_HTML_TAGS, attributes=SAFE_HTML_ATTRIBUTES, protocols=["http", "https", "mailto"], strip=True)
    return re.sub(r'<a\s+([^>]*href="(?:https?://|mailto:)[^"]+"[^>]*)>', lambda match: f'<a {match.group(1)} target="_blank" rel="noopener noreferrer">', cleaned)


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    quoted = quote(filename)
    if quoted != filename:
        return f"{disposition}; filename*=utf-8''{quoted}"
    return f'{disposition}; filename="{filename}"'


def decode_text_file(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try: return payload.decode(encoding)
        except UnicodeDecodeError: continue
    raise UnicodeDecodeError("unknown", payload, 0, len(payload), "unsupported text encoding")


def render_description(value: str) -> str:
    if re.search(r"</?[a-zA-Z][^>]*>", value):
        return clean_html(value)
    return html.escape(value).replace("\n", "<br>")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    try:
        trusted = any(ip_address(peer) in ip_network(value.strip()) for value in settings.trusted_proxy_cidrs.split(",") if value.strip())
    except ValueError:
        trusted = False
    forwarded = request.headers.get("X-Real-IP") if trusted else None
    try:
        return str(ip_address(forwarded)) if forwarded else peer
    except ValueError:
        return peer


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid4().hex
    client_token = request_client_id.set(request.headers.get("X-Client-ID"))
    ip_token = request_ip_address.set(client_ip(request))
    trace_token = request_trace_id.set(request.state.request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    finally:
        request_trace_id.reset(trace_token)
        request_ip_address.reset(ip_token)
        request_client_id.reset(client_token)


@app.exception_handler(ApiError)
async def api_error(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, "details": exc.details, "request_id": request.state.request_id})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(x) for x in item["loc"] if x != "body"), "message": item["msg"]} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "提交内容不完整或格式不正确", "details": {"fields": details}, "request_id": request.state.request_id})


Db = Annotated[Session, Depends(get_db)]


def now() -> datetime: return datetime.now(UTC)


def realtime_scopes(action: str) -> list[str]:
    if action.startswith(("CLASS_", "ROSTER_")): return ["classes", "members", "dashboard", "audit"]
    if action.startswith("TEAM_") or action.startswith("TOPIC_") or action == "TEAMS_AUTO_GROUPED": return ["teams", "members", "dashboard", "audit"]
    if action.startswith("ASSIGNMENT_"): return ["assignments", "dashboard", "audit"]
    if action.startswith("SUBMISSION_"): return ["submissions", "assignments", "dashboard", "grades", "audit"]
    if action.startswith(("PEER_", "REVIEW_")): return ["reviews", "submissions", "grades", "dashboard", "audit"]
    if action.startswith(("TEACHER_", "GRADE_", "GRADES_")): return ["submissions", "grades", "dashboard", "audit"]
    return ["audit"]


def realtime_class_id(db: Session, kind: str, oid: str, changes: dict) -> UUID | None:
    try:
        object_id = UUID(str(oid))
    except (TypeError, ValueError):
        return None
    if kind == "class": return object_id
    if changes.get("class_id"):
        try: return UUID(str(changes["class_id"]))
        except (TypeError, ValueError): pass
    if kind == "assignment":
        item = db.get(Assignment, object_id); return item.class_id if item else None
    if kind == "team":
        item = db.get(Team, object_id); return item.class_id if item else None
    if kind == "topic":
        item = db.get(Topic, object_id); return item.class_id if item else None
    if kind == "submission":
        item = db.get(Submission, object_id); assignment = db.get(Assignment, item.assignment_id) if item else None; return assignment.class_id if assignment else None
    if kind == "submission_assessment":
        item = db.get(SubmissionAssessment, object_id); assignment = db.get(Assignment, item.assignment_id) if item else None; return assignment.class_id if assignment else None
    if kind in {"review_campaign", "peer_review"}:
        campaign = db.get(ReviewCampaign, object_id) if kind == "review_campaign" else None
        if kind == "peer_review":
            review = db.get(PeerReview, object_id); campaign = db.get(ReviewCampaign, review.campaign_id) if review else None
        return campaign.class_id if campaign else None
    if kind in {"team_request", "class_join_request"}:
        model = TeamRequest if kind == "team_request" else ClassJoinRequest
        item = db.get(model, object_id); return item.class_id if item else None
    return None


def audit(db: Session, user: User | None, action: str, kind: str, oid: str, changes: dict | None = None):
    class_id = realtime_class_id(db, kind, oid, changes or {})
    course = db.get(TeachingClass, class_id) if class_id else None
    db.add(AuditLog(actor_id=user.id if user else None, class_id=class_id, class_semester=course.semester if course else None, class_name=course.name if course else None, action=action, object_type=kind, object_id=oid, changes=changes or {}, request_id=request_trace_id.get(), ip_address=request_ip_address.get()))
    if class_id:
        publish_event(db, class_id=class_id, scopes=realtime_scopes(action), resource_type=kind, resource_id=oid, source_client_id=request_client_id.get())
    elif user:
        publish_event(db, user_id=user.id, scopes=["audit"], resource_type=kind, resource_id=oid, source_client_id=request_client_id.get())


def notify(db: Session, uid: UUID, kind: str, title: str, object_type: str | None = None, object_id: str | None = None):
    db.add(Notification(user_id=uid, kind=kind, title=title, object_type=object_type, object_id=object_id))
    scopes = ["notifications"]
    if kind.startswith("TEAM_") or kind == "TOPIC_REQUIRED": scopes.extend(["teams", "members", "dashboard"])
    if kind.startswith("REVIEW_"): scopes.extend(["reviews", "dashboard"])
    if kind.startswith("GRADE_"): scopes.extend(["grades", "dashboard"])
    publish_event(db, user_id=uid, scopes=scopes, resource_type=object_type or "notification", resource_id=object_id, source_client_id=request_client_id.get())


def current_user(session_id: Annotated[str | None, Cookie()] = None, db: Session = Depends(get_db)) -> User:
    if not session_id: raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id), LoginSession.revoked_at.is_(None), LoginSession.expires_at > now()))
    user = db.get(User, session.user_id) if session else None
    if not user or user.status != "ACTIVE": raise ApiError(401, "SESSION_INVALID", "会话已失效")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


@app.get("/api/v1/events")
async def realtime_events(request: Request, class_id: UUID = Query(), session_id: Annotated[str | None, Cookie()] = None):
    session_hash = token_hash(session_id or "")
    with SessionLocal() as db:
        login_session = db.scalar(select(LoginSession).where(LoginSession.token_hash == session_hash, LoginSession.revoked_at.is_(None), LoginSession.expires_at > now()))
        user = db.get(User, login_session.user_id) if login_session else None
        if not user or user.status != "ACTIVE": raise ApiError(401, "SESSION_INVALID", "会话已失效")
        require_class(db, user, class_id)
        user_id, user_role = user.id, user.role
    subscriber = realtime_hub.subscribe(user_id, user_role, class_id)

    async def stream():
        started = asyncio.get_running_loop().time()
        ready = {"id": uuid4().hex, "type": "sync_required", "scopes": ["current_view", "notifications"]}
        yield f"event: sync_required\nid: {ready['id']}\ndata: {json.dumps(ready, separators=(',', ':'))}\n\n"
        try:
            while asyncio.get_running_loop().time() - started < 300:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(subscriber.queue.get(), timeout=15)
                    event_type = payload.get("type", "invalidate")
                    yield f"event: {event_type}\nid: {payload.get('id', '')}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                except TimeoutError:
                    with SessionLocal() as session_db:
                        active = session_db.scalar(select(LoginSession.id).where(LoginSession.token_hash == session_hash, LoginSession.revoked_at.is_(None), LoginSession.expires_at > now()).limit(1))
                    if not active:
                        payload = {"id": uuid4().hex, "type": "auth_expired", "scopes": []}
                        yield f"event: auth_expired\nid: {payload['id']}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                        break
                    yield ": heartbeat\n\n"
        finally:
            realtime_hub.unsubscribe(subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def csrf_user(user: CurrentUser, db: Db, session_id: Annotated[str | None, Cookie()] = None, x_csrf_token: Annotated[str | None, Header()] = None) -> User:
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id or ""), LoginSession.user_id == user.id, LoginSession.revoked_at.is_(None)))
    if not session or not x_csrf_token or not secrets.compare_digest(session.csrf_token, x_csrf_token): raise ApiError(403, "CSRF_INVALID", "请求校验失败，请刷新后重试")
    return user


CsrfUser = Annotated[User, Depends(csrf_user)]


def teacher(user: User):
    if user.role != "TEACHER": raise ApiError(403, "TEACHER_REQUIRED", "仅教师可执行此操作")


def user_class(db: Session, user: User, cid: UUID | None = None) -> TeachingClass | None:
    q = select(TeachingClass).where(TeachingClass.teacher_id == user.id) if user.role == "TEACHER" else select(TeachingClass).join(ClassMember).where(ClassMember.user_id == user.id, ClassMember.status == "ACTIVE")
    if cid: q = q.where(TeachingClass.id == cid)
    return db.scalar(q.order_by(TeachingClass.created_at.desc()))


def require_class(db: Session, user: User, cid: UUID | None = None) -> TeachingClass:
    item = user_class(db, user, cid)
    if not item: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可访问的教学班")
    return item


def require_writable_class(db: Session, user: User, cid: UUID | None = None) -> TeachingClass:
    course = require_class(db, user, cid)
    if course.status != "ACTIVE": raise ApiError(409, "CLASS_ARCHIVED", "教学班已归档，当前只能查看历史内容")
    return course


def require_team_window(course: TeachingClass, user: User) -> None:
    if user.role == "STUDENT" and course.team_deadline and course.team_deadline <= now():
        raise ApiError(409, "TEAM_DEADLINE_PASSED", "组队已截止，请联系教师调整")


def membership(db: Session, cid: UUID, uid: UUID):
    row = db.execute(select(TeamMember, Team).join(Team).where(TeamMember.class_id == cid, TeamMember.user_id == uid, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")).first()
    return (row[0], row[1]) if row else None


def require_team(db: Session, cid: UUID, user: User):
    row = membership(db, cid, user.id)
    if not row: raise ApiError(403, "TEAM_REQUIRED", "请先加入小组")
    return row


def class_json(x: TeachingClass, *, member_count: int | None = None, assignment_count: int | None = None, deletable: bool | None = None):
    item = {"id": str(x.id), "course": x.course, "semester": x.semester, "name": x.name, "invite_code": x.invite_code, "status": x.status, "team_deadline": x.team_deadline, "topic_public": x.topic_public, "invite_requires_approval": x.invite_requires_approval, "version": x.version}
    if member_count is not None: item["member_count"] = member_count
    if assignment_count is not None: item["assignment_count"] = assignment_count
    if deletable is not None: item["deletable"] = deletable
    return item


def team_json(db: Session, x: Team, viewer: User):
    leader = db.get(User, x.leader_id)
    count = db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == x.id, TeamMember.status == "ACTIVE")) or 0
    topic = db.scalar(select(Topic).where(Topic.team_id == x.id))
    pending = db.scalar(select(func.count()).select_from(TeamRequest).where(TeamRequest.team_id == x.id, TeamRequest.status == "PENDING")) or 0
    course = db.get(TeachingClass, x.class_id)
    own_team = membership(db, x.class_id, viewer.id)
    can_view_topic = viewer.role == "TEACHER" or (own_team and own_team[1].id == x.id) or bool(course and course.topic_public)
    return {"id": str(x.id), "name": x.name, "leader_id": str(x.leader_id), "leader_name": leader.display_name, "member_count": count, "open_recruitment": x.open_recruitment, "status": x.status, "is_leader": x.leader_id == viewer.id, "pending_count": pending, "topic": None if not topic or not can_view_topic else {"id": str(topic.id), "name": topic.name, "description": topic.description, "status": topic.review_status, "reason": topic.review_reason}, "version": x.version}


class LoginIn(BaseModel):
    account: str; password: str; role: Literal["teacher", "student"] | None = None
class ClassIn(BaseModel):
    semester: str = Field(min_length=2, max_length=40); name: str = Field(min_length=2, max_length=100); team_deadline: datetime | None = None; topic_public: bool = False; invite_requires_approval: bool = True
class TeachingMaterialFolderIn(BaseModel):
    class_id: UUID
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
class TeamIn(BaseModel):
    class_id: UUID; name: str = Field(min_length=2, max_length=40); open_recruitment: bool = True
class AutoGroupIn(BaseModel):
    group_size: int = Field(default=6, ge=2, le=20)
class TopicIn(BaseModel):
    name: str = Field(min_length=2, max_length=100); description: str = Field("", max_length=1000)
class AssignmentFields(BaseModel):
    title: str = Field(min_length=2, max_length=100); description: str = Field(min_length=1, max_length=5000); submitter_type: Literal["TEAM", "INDIVIDUAL"]; starts_at: datetime | None = None; due_at: datetime; allow_late: bool = False; publish: bool = True
    auto_review_enabled: bool = False
    auto_review_mode: Literal["TEAM"] | None = None
    auto_review_criteria_text: str = Field("", max_length=5000)
    auto_review_due_at: datetime | None = None
class AssignmentIn(AssignmentFields):
    class_id: UUID
class AssignmentBulkIn(AssignmentFields):
    class_ids: list[UUID] = Field(min_length=1)
class AllocatedCampaignIn(BaseModel):
    assignment_id: UUID
    mode: Literal["TEAM"]
    criteria_text: str = Field("", max_length=5000)
    criteria_file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    due_at: datetime
class ReviewIn(BaseModel):
    score: float | None = Field(None, ge=0, le=100)
    comment: str = Field(max_length=2000)
    reviewee_id: UUID | None = None
    scores: dict[str, float] | None = None
class SubmissionAssessmentIn(BaseModel):
    grade: Literal["A", "B", "C", "D", "E"]
    comment: str = Field("", max_length=2000)
class SubmissionAnnotationIn(BaseModel):
    id: UUID | None = None
    file_id: UUID
    kind: Literal["PDF_TEXT_OR_REGION", "RICH_TEXT_RANGE"]
    mark_type: Literal["HIGHLIGHT", "UNDERLINE", "STRIKETHROUGH", "COMMENT"] | None = None
    color: Literal["YELLOW", "GREEN", "RED", "BLUE"] = "YELLOW"
    anchor: dict
    comment: str = Field("", max_length=20000)
class SubmissionFeedbackIn(BaseModel):
    revision: int = Field(ge=0)
    grade: Literal["A", "B", "C", "D", "E"]
    comment: str = Field("", max_length=20000)
    annotations: list[SubmissionAnnotationIn] = Field(default_factory=list, max_length=500)
class PeerSubmissionAssessmentIn(SubmissionAssessmentIn):
    reviewee_id: UUID
class CoefficientIn(BaseModel):
    coefficient: Decimal = Field(ge=0, decimal_places=2)
    version: int = Field(ge=1)
class GradePublishIn(BaseModel):
    reason: str = Field("", max_length=500)
class AssignmentUpdateIn(BaseModel):
    class_id: UUID | None = None
    title: str | None = Field(None, min_length=2, max_length=100); description: str | None = Field(None, min_length=1, max_length=5000); starts_at: datetime | None = None; due_at: datetime | None = None; allow_late: bool | None = None; submitter_type: Literal["TEAM", "INDIVIDUAL"] | None = None; version: int
    auto_review_enabled: bool | None = None
    auto_review_mode: Literal["TEAM"] | None = None
    auto_review_criteria_text: str | None = Field(None, max_length=5000)
    auto_review_due_at: datetime | None = None
class SubmissionDocumentIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
class SubmissionDocumentUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    markdown_content: str = Field(max_length=settings.max_file_size_bytes)
class ReasonIn(BaseModel): reason: str = Field(min_length=2, max_length=500)
class PasswordIn(BaseModel): current_password: str; new_password: str = Field(min_length=8, max_length=128)
class ClassJoinIn(BaseModel): invite_code: str = Field(min_length=4, max_length=12)
class InviteIn(BaseModel): student_id: UUID
class TransferIn(BaseModel): new_leader_id: UUID
class ClassUpdateIn(BaseModel):
    version: int = Field(ge=1)
    semester: str | None = Field(None, min_length=2, max_length=40)
    name: str | None = Field(None, min_length=2, max_length=100)
    team_deadline: datetime | None = None
    topic_public: bool | None = None
    invite_requires_approval: bool | None = None
    status: Literal["ACTIVE", "ARCHIVED"] | None = None
class MemberCreateIn(BaseModel):
    student_no: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
class MemberUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
class MaterialTypeIn(BaseModel):
    material_type: Literal["TASK", "ATTACHMENT", "CRITERIA"]
class MenuPermissionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: dict[Literal["TEACHER", "STUDENT"], list[str]]


@app.get("/health/live")
def live(): return {"status": "ok", "service": "coursework-api"}


@app.get("/health/ready")
def ready(response: Response):
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        storage.bucket_reachable()
        return {"status": "ready", "database": "ok", "storage": "ok"}
    except Exception:
        response.status_code = 503; return {"status": "not_ready", "database": "unavailable", "storage": "unknown"}


@app.post("/api/v1/auth/login")
def login(data: LoginIn, response: Response, db: Db):
    user = db.scalar(select(User).where(User.login_name == data.account.strip()))
    if user and user.locked_until and user.locked_until > now(): raise ApiError(429, "LOGIN_LOCKED", "登录失败次数过多，请稍后重试")
    if not user or not verify_password(user.password_hash, data.password):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= 5: user.failed_logins, user.locked_until = 0, now() + timedelta(minutes=15)
            db.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码错误")
    if data.role and data.role != user.role.lower(): raise ApiError(403, "ROLE_MISMATCH", "所选身份与账号不匹配")
    user.failed_logins, user.locked_until = 0, None
    token, hashed, csrf, expires = new_session()
    db.add(LoginSession(user_id=user.id, token_hash=hashed, csrf_token=csrf, expires_at=expires)); db.commit()
    response.set_cookie("session_id", token, httponly=True, secure=settings.secure_cookies, samesite="lax", max_age=settings.session_hours * 3600, path="/")
    return {"user": {"id": str(user.id), "account": user.login_name, "name": user.display_name, "role": user.role}, "csrf_token": csrf}


@app.get("/api/v1/auth/session")
def auth_session(user: CurrentUser, db: Db, session_id: Annotated[str | None, Cookie()] = None):
    x = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id or ""), LoginSession.revoked_at.is_(None)))
    return {"user": {"id": str(user.id), "account": user.login_name, "name": user.display_name, "role": user.role}, "csrf_token": x.csrf_token}


@app.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response, user: CsrfUser, db: Db, session_id: Annotated[str | None, Cookie()] = None):
    x = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id or "")))
    if x: x.revoked_at = now(); db.commit()
    response.delete_cookie("session_id", path="/")
    response.status_code = 204
    return response


@app.post("/api/v1/auth/password", status_code=204)
def password(data: PasswordIn, user: CsrfUser, db: Db):
    if not verify_password(user.password_hash, data.current_password): raise ApiError(422, "CURRENT_PASSWORD_INVALID", "当前密码不正确")
    user.password_hash = hash_password(data.new_password)
    audit(db, user, "PASSWORD_CHANGED", "user", str(user.id))
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/menu-permissions")
def menu_permissions(user: CurrentUser, db: Db):
    return menu_permissions_payload(db, user)


@app.put("/api/v1/menu-permissions")
def update_menu_permissions(data: MenuPermissionsIn, user: CsrfUser, db: Db):
    teacher(user)
    expected_roles = {"TEACHER", "STUDENT"}
    if set(data.roles) != expected_roles:
        raise ApiError(422, "MENU_ROLES_REQUIRED", "必须同时配置教师和学生角色")
    applicable = {role: {item["key"] for item in MENU_CATALOG if role in item["roles"]} for role in expected_roles}
    normalized: dict[str, list[str]] = {}
    for role in expected_roles:
        keys = data.roles[role]
        if len(keys) != len(set(keys)) or not set(keys).issubset(applicable[role]):
            raise ApiError(422, "MENU_KEY_INVALID", "菜单配置包含无效模块")
        if not keys:
            raise ApiError(422, "MENU_EMPTY", "每个角色至少保留一个可访问模块")
        normalized[role] = [item["key"] for item in MENU_CATALOG if item["key"] in keys and role in item["roles"]]

    previous = menu_permissions_by_role(db)
    existing = {(item.role, item.menu_key): item for item in db.scalars(select(RoleMenuPermission)).all()}
    for role in expected_roles:
        enabled_keys = set(normalized[role])
        for menu_key in applicable[role]:
            item = existing.get((role, menu_key))
            if item:
                item.enabled = menu_key in enabled_keys
                item.updated_by = user.id
            else:
                db.add(RoleMenuPermission(role=role, menu_key=menu_key, enabled=menu_key in enabled_keys, updated_by=user.id))
    audit(db, user, "ROLE_MENU_PERMISSIONS_UPDATED", "role_menu_permissions", "global", {"before": previous, "after": normalized})
    publish_event(db, scopes=["menu_permissions"], roles=["TEACHER", "STUDENT"], resource_type="role_menu_permissions", resource_id="global", source_client_id=request_client_id.get())
    db.commit()
    return menu_permissions_payload(db, user)


@app.get("/api/v1/classes")
def classes(user: CurrentUser, db: Db):
    q = select(TeachingClass).where(TeachingClass.teacher_id == user.id) if user.role == "TEACHER" else select(TeachingClass).join(ClassMember).where(ClassMember.user_id == user.id, ClassMember.status == "ACTIVE")
    courses = db.scalars(q.order_by(
        TeachingClass.semester.desc(),
        TeachingClass.name.asc(),
        TeachingClass.created_at.desc(),
        TeachingClass.id.desc(),
    )).all()
    if not courses: return {"items": [], "total": 0}
    class_ids = [x.id for x in courses]
    member_counts = dict(db.execute(select(ClassMember.class_id, func.count()).where(ClassMember.class_id.in_(class_ids), ClassMember.status == "ACTIVE").group_by(ClassMember.class_id)).all())
    assignment_counts = dict(db.execute(select(Assignment.class_id, func.count()).where(Assignment.class_id.in_(class_ids)).group_by(Assignment.class_id)).all())
    if user.role == "STUDENT":
        items = [class_json(x, member_count=member_counts.get(x.id, 0), assignment_count=assignment_counts.get(x.id, 0), deletable=False) for x in courses]
        return {"items": items, "total": len(items)}
    member_history_counts = dict(db.execute(select(ClassMember.class_id, func.count()).where(ClassMember.class_id.in_(class_ids)).group_by(ClassMember.class_id)).all())
    import_counts = dict(db.execute(select(ImportBatch.class_id, func.count()).where(ImportBatch.class_id.in_(class_ids)).group_by(ImportBatch.class_id)).all())
    team_counts = dict(db.execute(select(Team.class_id, func.count()).where(Team.class_id.in_(class_ids)).group_by(Team.class_id)).all())
    items = [class_json(x, member_count=member_counts.get(x.id, 0), assignment_count=assignment_counts.get(x.id, 0), deletable=not any((member_history_counts.get(x.id, 0), assignment_counts.get(x.id, 0), import_counts.get(x.id, 0), team_counts.get(x.id, 0)))) for x in courses]
    return {"items": items, "total": len(items)}


@app.post("/api/v1/classes", status_code=201)
def create_class(data: ClassIn, user: CsrfUser, db: Db):
    teacher(user); x = TeachingClass(teacher_id=user.id, semester=data.semester.strip(), name=data.name.strip(), invite_code=secrets.token_hex(4).upper(), team_deadline=data.team_deadline, topic_public=data.topic_public, invite_requires_approval=data.invite_requires_approval)
    db.add(x); db.flush(); audit(db, user, "CLASS_CREATED", "class", str(x.id)); db.commit(); return class_json(x)


@app.post("/api/v1/classes/join")
def join_class(data: ClassJoinIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可以通过邀请码加入教学班")
    course = db.scalar(select(TeachingClass).where(TeachingClass.invite_code == data.invite_code.strip().upper()).with_for_update())
    if not course: raise ApiError(404, "INVITE_CODE_INVALID", "邀请码无效")
    if course.status != "ACTIVE": raise ApiError(409, "CLASS_ARCHIVED", "教学班已归档，无法加入")
    member = db.scalar(select(ClassMember).where(ClassMember.class_id == course.id, ClassMember.user_id == user.id).with_for_update())
    if member and member.status == "ACTIVE": raise ApiError(409, "CLASS_MEMBER_EXISTS", "你已加入该教学班")
    if course.invite_requires_approval:
        pending = db.scalar(select(ClassJoinRequest).where(ClassJoinRequest.class_id == course.id, ClassJoinRequest.user_id == user.id, ClassJoinRequest.status == "PENDING").with_for_update())
        if pending: raise ApiError(409, "CLASS_JOIN_PENDING", "加入申请正在等待教师审核")
        request = ClassJoinRequest(class_id=course.id, user_id=user.id); db.add(request); audit(db, user, "CLASS_JOIN_REQUESTED", "class", str(course.id)); db.commit()
        return {"status": "PENDING", "class_id": str(course.id), "class_name": course.name}
    if member: member.status = "ACTIVE"
    else: db.add(ClassMember(class_id=course.id, user_id=user.id))
    audit(db, user, "CLASS_JOINED_BY_INVITE", "class", str(course.id)); db.commit()
    return {"status": "APPROVED", "class_id": str(course.id), "class_name": course.name}


@app.get("/api/v1/classes/{cid}/join-requests")
def class_join_requests(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); require_class(db, user, cid)
    rows = db.execute(select(ClassJoinRequest, User).join(User).where(ClassJoinRequest.class_id == cid).order_by(ClassJoinRequest.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "user_id": str(person.id), "student_no": person.login_name, "name": person.display_name, "status": item.status, "created_at": item.created_at} for item, person in rows]}


@app.post("/api/v1/classes/{cid}/join-requests/{rid}/decision")
def decide_class_join_request(cid: UUID, rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    request = db.scalar(select(ClassJoinRequest).where(ClassJoinRequest.id == rid, ClassJoinRequest.class_id == cid).with_for_update())
    if not request or request.status != "PENDING": raise ApiError(409, "CLASS_JOIN_NOT_PENDING", "该加入申请无法处理")
    request.status, request.resolved_at = decision, now()
    if decision == "APPROVED":
        member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == request.user_id).with_for_update())
        if member and member.status == "ACTIVE": raise ApiError(409, "CLASS_MEMBER_EXISTS", "该学生已加入教学班")
        if member: member.status = "ACTIVE"
        else: db.add(ClassMember(class_id=cid, user_id=request.user_id))
    audit(db, user, f"CLASS_JOIN_{decision}", "class_join_request", str(request.id)); db.commit()
    return {"id": str(request.id), "status": request.status}


@app.get("/api/v1/classes/current/context")
def context(user: CurrentUser, db: Db, class_id: UUID | None = Query(None)):
    course = user_class(db, user, class_id); m = membership(db, course.id, user.id) if course and user.role == "STUDENT" else None
    return {"user": {"id": str(user.id), "account": user.login_name, "name": user.display_name, "role": user.role}, "current_class": class_json(course) if course else None, "team_membership": None if not m else {"team_id": str(m[1].id), "team_name": m[1].name, "role": m[0].role}, "team_gate_required": bool(course and user.role == "STUDENT" and not m), "permissions": {"manage_class": user.role == "TEACHER", "access_coursework": user.role == "TEACHER" or bool(m)}}


@app.get("/api/v1/classes/{cid}/dashboard")
def dashboard(cid: UUID, user: CurrentUser, db: Db):
    course = require_class(db, user, cid)
    if user.role == "STUDENT": require_team(db, cid, user)
    members = db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE")) or 0
    teams = db.scalar(select(func.count()).select_from(Team).where(Team.class_id == cid, Team.status == "ACTIVE")) or 0
    ungrouped_members = db.scalar(
        select(func.count()).select_from(ClassMember).where(
            ClassMember.class_id == cid,
            ClassMember.status == "ACTIVE",
            ~select(TeamMember.id).where(
                TeamMember.class_id == cid,
                TeamMember.user_id == ClassMember.user_id,
                TeamMember.status == "ACTIVE",
            ).exists(),
        )
    ) or 0
    visible_assignment = or_(Assignment.starts_at.is_(None), Assignment.starts_at <= now())
    active_filters = [Assignment.class_id == cid, Assignment.status == "PUBLISHED", Assignment.due_at >= now()]
    if user.role == "STUDENT": active_filters.append(visible_assignment)
    active = db.scalar(select(func.count()).select_from(Assignment).where(*active_filters)) or 0
    latest_assignment = db.scalar(select(Assignment).where(*active_filters).order_by(Assignment.created_at.desc()).limit(1))
    assignment_expected = (members if latest_assignment.submitter_type == "INDIVIDUAL" else teams) if latest_assignment else 0
    assignment_submitted = db.scalar(select(func.count()).select_from(Submission).where(Submission.assignment_id == latest_assignment.id, Submission.status == "SUBMITTED")) if latest_assignment else 0

    history_filters = [Assignment.class_id == cid, Assignment.status.in_(["PUBLISHED", "CLOSED"])]
    if user.role == "STUDENT": history_filters.append(visible_assignment)
    recent_assignments = list(reversed(db.scalars(
        select(Assignment)
        .where(*history_filters)
        .order_by(Assignment.due_at.desc())
        .limit(6)
    ).all()))
    assignment_history = []
    for item in recent_assignments:
        expected = members if item.submitter_type == "INDIVIDUAL" else teams
        submitted = db.scalar(select(func.count()).select_from(Submission).where(Submission.assignment_id == item.id, Submission.status == "SUBMITTED")) or 0
        assignment_history.append({
            "id": str(item.id),
            "title": item.title,
            "due_at": item.due_at,
            "submitted": submitted,
            "expected": expected,
            "completion_rate": round(submitted * 100 / expected, 1) if expected else 0,
        })

    latest_submission = None
    if user.role == "TEACHER":
        submitted_rows = db.execute(
            select(Assignment, SubmissionVersion, Submission)
            .join(Submission, and_(Submission.assignment_id == Assignment.id, Submission.status == "SUBMITTED"))
            .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
            .where(
                Assignment.class_id == cid,
                Assignment.status.in_(["PUBLISHED", "CLOSED"]),
                Assignment.submitter_type == "INDIVIDUAL",
                ~select(SubmissionAssessment.id).where(
                    SubmissionAssessment.submission_version_id == SubmissionVersion.id,
                    SubmissionAssessment.kind == "TEACHER",
                    SubmissionAssessment.status == "PUBLISHED",
                ).exists(),
            )
        ).all()
        submitted_rows = [row for row in submitted_rows if db.scalar(select(VersionFile.file_id).where(VersionFile.version_id == row.SubmissionVersion.id).limit(1))]
        if submitted_rows:
            assignment, version, submission_item = min(
                submitted_rows,
                key=lambda row: (abs((row.Assignment.due_at - now()).total_seconds()), -row.SubmissionVersion.submitted_at.timestamp()),
            )
            owner = db.get(User, submission_item.owner_user_id) if submission_item.owner_user_id else db.get(Team, submission_item.owner_team_id)
            latest_submission = {
                "assignment_id": str(assignment.id), "assignment_title": assignment.title,
                "submission_version_id": str(version.id), "owner": owner.display_name if isinstance(owner, User) else owner.name,
                "submitted_at": version.submitted_at, "due_at": assignment.due_at,
            }

    latest_campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.class_id == cid, ReviewCampaign.due_at <= now()).order_by(ReviewCampaign.due_at.desc()).limit(1))
    review_expected = review_completed = 0
    if latest_campaign:
        if latest_campaign.assignment_snapshot_at is not None:
            allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == latest_campaign.id)).all()
            review_expected = sum(item.status != "SKIPPED" for item in allocations)
            review_completed = sum(item.status == "COMPLETED" for item in allocations)
        else:
            review_expected = db.scalar(select(func.count(func.distinct(TeamMember.user_id))).where(TeamMember.class_id == cid, TeamMember.status == "ACTIVE")) or 0
            review_completed = db.scalar(select(func.count(func.distinct(PeerReview.reviewer_id))).where(PeerReview.campaign_id == latest_campaign.id, PeerReview.status == "VALID")) or 0
    latest_campaign_assignment = db.get(Assignment, latest_campaign.assignment_id) if latest_campaign else None
    return {
        "class": class_json(course),
        "summary": {
            "member_count": members,
            "team_count": teams,
            "ungrouped_member_count": ungrouped_members,
            "active_assignments": active,
            "submission_rate": round((assignment_submitted or 0) * 100 / assignment_expected, 1) if assignment_expected else 0,
            "submission_assignment_title": latest_assignment.title if latest_assignment else None,
            "submission_assignment_due_at": latest_assignment.due_at if latest_assignment else None,
            "peer_review_rate": round(review_completed * 100 / review_expected, 1) if review_expected else 0,
            "peer_review_assignment_title": latest_campaign_assignment.title if latest_campaign_assignment else None,
            "peer_review_due_at": latest_campaign.due_at if latest_campaign else None,
            "latest_submission": latest_submission,
        },
        "assignment_history": assignment_history,
    }


def parse_roster(content: bytes, filename: str):
    if filename.lower().endswith(".csv"):
        return [(str(r.get("学号", "")).strip(), str(r.get("姓名", "")).strip()) for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig")))]
    if filename.lower().endswith(".xlsx"):
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for sheet in workbook.worksheets:
            sheet.reset_dimensions()
            row_iter = sheet.iter_rows(values_only=True)
            first_row = next(row_iter, None)
            headers = [str(x or "").strip() for x in first_row or ()]
            if "学号" not in headers or "姓名" not in headers: continue
            sid, name = headers.index("学号"), headers.index("姓名")
            return [(str(row[sid] or "").strip(), str(row[name] or "").strip()) for row in row_iter if len(row) > max(sid, name) and any(value is not None and str(value).strip() for value in row)]
        raise ValueError("missing roster headers")
    raise ApiError(422, "ROSTER_FORMAT_INVALID", "仅支持 XLSX 或 CSV 名单")


@app.post("/api/v1/classes/{cid}/members/import-preview", status_code=201)
async def import_preview(cid: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...)):
    teacher(user); require_writable_class(db, user, cid)
    try: raw = parse_roster(await file.read(), file.filename or "")
    except (UnicodeDecodeError, ValueError, IndexError): raise ApiError(422, "ROSTER_PARSE_FAILED", "无法读取名单，请确认列名为学号、姓名")
    seen, rows = set(), []
    for line, (sid, name) in enumerate(raw, 2):
        status, reason = "READY", "将创建账号"
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,32}", sid) or not name: status, reason = "ERROR", "学号或姓名格式错误"
        elif sid in seen: status, reason = "DUPLICATE", "文件内学号重复"
        else:
            old = db.scalar(select(User).where(User.login_name == sid))
            if old:
                existing_member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == old.id))
                status, reason = ("EXISTS", "已在当前教学班") if existing_member and existing_member.status == "ACTIVE" else ("JOIN", "加入已有账号")
        seen.add(sid); rows.append({"row": line, "student_no": sid, "name": name, "status": status, "reason": reason})
    batch = ImportBatch(class_id=cid, created_by=user.id, rows=rows); db.add(batch); db.commit()
    return {"batch_id": str(batch.id), "rows": rows, "summary": {s: sum(r["status"] == s for r in rows) for s in ["READY", "JOIN", "EXISTS", "DUPLICATE", "ERROR"]}}


@app.post("/api/v1/classes/{cid}/members/import/{bid}/confirm")
def import_confirm(cid: UUID, bid: UUID, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid); batch = db.scalar(select(ImportBatch).where(ImportBatch.id == bid, ImportBatch.class_id == cid).with_for_update())
    if not batch or batch.status != "PREVIEWED": raise ApiError(409, "IMPORT_NOT_CONFIRMABLE", "该导入批次已处理或不存在")
    created = joined = skipped = 0
    for row in batch.rows:
        if row["status"] not in {"READY", "JOIN"}: skipped += 1; continue
        student = db.scalar(select(User).where(User.login_name == row["student_no"]))
        if not student:
            student = User(login_name=row["student_no"], display_name=row["name"], password_hash=hash_password(row["student_no"]), role="STUDENT"); db.add(student); db.flush(); created += 1
        elif student.role != "STUDENT":
            row["status"], row["reason"] = "ERROR", "账号已被非学生用户使用"; skipped += 1; continue
        else:
            student.display_name = row["name"]
        existing_member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == student.id))
        if existing_member:
            if existing_member.status != "ACTIVE": existing_member.status = "ACTIVE"; joined += 1
        else: db.add(ClassMember(class_id=cid, user_id=student.id)); joined += 1
    batch.rows = [dict(row) for row in batch.rows]; batch.status = "CONFIRMED"; audit(db, user, "ROSTER_IMPORTED", "class", str(cid), {"created": created, "joined": joined, "skipped": skipped}); db.commit(); return {"created": created, "joined": joined, "skipped": skipped}


@app.get("/api/v1/classes/{cid}/members/import/{bid}/result.csv")
def import_result(cid: UUID, bid: UUID, user: CurrentUser, db: Db):
    teacher(user); require_class(db, user, cid)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.id == bid, ImportBatch.class_id == cid))
    if not batch: raise ApiError(404, "IMPORT_NOT_FOUND", "导入记录不存在")
    stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(["行号", "学号", "姓名", "状态", "结果"])
    for row in batch.rows: writer.writerow([row["row"], row["student_no"], row["name"], row["status"], row["reason"]])
    return Response(content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="roster-{bid}.csv"'})


@app.get("/api/v1/classes/{cid}/members")
def members(cid: UUID, user: CurrentUser, db: Db):
    require_class(db, user, cid)
    rows = db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE").order_by(User.login_name)).all()
    items = [{"id": str(s.id), "student_no": s.login_name, "name": s.display_name, "status": m.status, "team": membership(db, cid, s.id)[1].name if membership(db, cid, s.id) else None, "joined_at": m.joined_at.isoformat()} for m, s in rows]
    return {"items": items, "total": len(items)}


def member_detail(db: Session, cid: UUID, uid: UUID):
    row = db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == cid, ClassMember.user_id == uid, ClassMember.status == "ACTIVE")).first()
    if not row: raise ApiError(404, "MEMBER_NOT_FOUND", "未找到学生")
    member, student = row; team = membership(db, cid, uid)
    return member, student, {"id": str(student.id), "student_no": student.login_name, "name": student.display_name, "status": member.status, "team": team[1].name if team else None, "joined_at": member.joined_at.isoformat()}


@app.post("/api/v1/classes/{cid}/members", status_code=201)
def create_member(cid: UUID, data: MemberCreateIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    student_no, name = data.student_no.strip(), data.name.strip()
    if not name: raise ApiError(422, "MEMBER_NAME_REQUIRED", "请填写学生姓名")
    student = db.scalar(select(User).where(User.login_name == student_no).with_for_update())
    created = False
    if student and student.role != "STUDENT": raise ApiError(409, "ACCOUNT_CONFLICT", "该学号已被其他身份使用")
    if not student:
        student = User(login_name=student_no, display_name=name, password_hash=hash_password(student_no), role="STUDENT")
        db.add(student); db.flush(); created = True
    else:
        student.display_name = name
    class_member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == student.id).with_for_update())
    if class_member and class_member.status == "ACTIVE": raise ApiError(409, "MEMBER_EXISTS", "该学生已在当前教学班")
    if class_member: class_member.status = "ACTIVE"
    else: db.add(ClassMember(class_id=cid, user_id=student.id))
    audit(db, user, "CLASS_MEMBER_ADDED", "class", str(cid), {"user_id": str(student.id), "created_account": created}); db.commit()
    return member_detail(db, cid, student.id)[2]


@app.get("/api/v1/classes/{cid}/members/{uid}")
def get_member(cid: UUID, uid: UUID, user: CurrentUser, db: Db):
    require_class(db, user, cid)
    return member_detail(db, cid, uid)[2]


@app.patch("/api/v1/classes/{cid}/members/{uid}")
def update_member(cid: UUID, uid: UUID, data: MemberUpdateIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    _, student, _ = member_detail(db, cid, uid)
    name = data.name.strip()
    if not name: raise ApiError(422, "MEMBER_NAME_REQUIRED", "请填写学生姓名")
    old_name = student.display_name; student.display_name = name
    audit(db, user, "CLASS_MEMBER_UPDATED", "class", str(cid), {"user_id": str(uid), "old_name": old_name, "name": student.display_name}); db.commit()
    return member_detail(db, cid, uid)[2]


@app.get("/api/v1/classes/{cid}/members/{uid}/portfolio")
def student_portfolio(cid: UUID, uid: UUID, user: CurrentUser, db: Db):
    from app.student_portfolio import portfolio
    teacher(user); require_class(db, user, cid)
    return portfolio(db, cid, uid)


@app.get("/api/v1/classes/{cid}/members/{uid}/portfolio.zip")
def export_student_portfolio(cid: UUID, uid: UUID, user: CurrentUser, db: Db):
    from app.student_portfolio import export_portfolios
    teacher(user); course = require_class(db, user, cid)
    member_detail(db, cid, uid)
    return export_portfolios(db, course, user, uid)


@app.get("/api/v1/classes/{cid}/portfolio.zip")
def export_class_portfolio(cid: UUID, user: CurrentUser, db: Db):
    from app.student_portfolio import export_portfolios
    teacher(user); course = require_class(db, user, cid)
    return export_portfolios(db, course, user)


@app.delete("/api/v1/classes/{cid}/members/{uid}", status_code=204)
def delete_member(cid: UUID, uid: UUID, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    class_member, student, _ = member_detail(db, cid, uid)
    team = membership(db, cid, uid)
    if team and team[1].leader_id == uid: raise ApiError(409, "TEAM_LEADER_TRANSFER_REQUIRED", "该学生是组长，请先移交组长或解散小组")
    if team:
        team[0].status = "REMOVED"; team[1].version += 1
    class_member.status = "REMOVED"
    db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == cid, TeamRequest.applicant_id == uid, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now()))
    notify(db, uid, "CLASS_MEMBER_REMOVED", "你已被移出教学班")
    audit(db, user, "CLASS_MEMBER_REMOVED", "class", str(cid), {"user_id": str(uid), "student_no": student.login_name}); db.commit()
    return Response(status_code=204)


@app.post("/api/v1/classes/{cid}/members/{uid}/reset-password", status_code=204)
def reset_password(cid: UUID, uid: UUID, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid); _, student, _ = member_detail(db, cid, uid)
    student.password_hash = hash_password(student.login_name)
    audit(db, user, "PASSWORD_RESET", "user", str(uid))
    db.execute(delete(LoginSession).where(LoginSession.user_id == uid))
    db.commit()
    return Response(status_code=204)


@app.get("/api/v1/teams")
def teams(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    query = select(Team).where(Team.class_id == class_id, Team.status == "ACTIVE")
    if user.role == "STUDENT":
        own_team = membership(db, class_id, user.id)
        if own_team:
            query = query.where(Team.id == own_team[1].id)
    items = db.scalars(query.order_by(Team.created_at)).all()
    return {"items": [team_json(db, x, user) for x in items], "total": len(items)}


@app.post("/api/v1/teams", status_code=201)
def create_team(data: TeamIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可创建小组")
    course = require_writable_class(db, user, data.class_id); require_team_window(course, user)
    if membership(db, course.id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
    x = Team(class_id=course.id, leader_id=user.id, name=data.name.strip(), normalized_name="".join(data.name.casefold().split()), open_recruitment=data.open_recruitment); db.add(x)
    try:
        db.flush(); db.add(TeamMember(team_id=x.id, class_id=course.id, user_id=user.id, role="LEADER")); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == course.id, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); notify(db, user.id, "TOPIC_REQUIRED", "小组已创建，请提交选题", "team", str(x.id)); audit(db, user, "TEAM_CREATED", "team", str(x.id)); db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "TEAM_NAME_EXISTS", "小组名称已被使用")
    return team_json(db, x, user)


@app.post("/api/v1/classes/{cid}/teams/auto-group", status_code=201)
def auto_group_teams(cid: UUID, data: AutoGroupIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    grouped_user_ids = select(TeamMember.user_id).join(Team).where(TeamMember.class_id == cid, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")
    students = db.scalars(select(User).join(ClassMember).where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE", User.id.not_in(grouped_user_ids)).order_by(User.login_name, User.id)).all()
    if not students: return {"created": 0, "assigned": 0, "teams": []}
    existing_names = set(db.scalars(select(Team.normalized_name).where(Team.class_id == cid)).all())
    created = []
    next_number = 1
    for offset in range(0, len(students), data.group_size):
        members = students[offset:offset + data.group_size]
        while f"小组{next_number}" in existing_names: next_number += 1
        name = f"小组{next_number}"
        existing_names.add(name); next_number += 1
        team = Team(class_id=cid, leader_id=members[0].id, name=name, normalized_name=name, open_recruitment=False, max_members=data.group_size)
        db.add(team); db.flush()
        for index, student in enumerate(members):
            db.add(TeamMember(team_id=team.id, class_id=cid, user_id=student.id, role="LEADER" if index == 0 else "MEMBER"))
            notify(db, student.id, "TEAM_ASSIGNED", f"教师已将你分入「{name}」", "team", str(team.id))
        created.append({"id": str(team.id), "name": name, "member_count": len(members)})
    db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == cid, TeamRequest.applicant_id.in_([student.id for student in students]), TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now()))
    audit(db, user, "TEAMS_AUTO_GROUPED", "class", str(cid), {"group_size": data.group_size, "assigned": len(students), "created": len(created)})
    db.commit()
    return {"created": len(created), "assigned": len(students), "teams": created}


@app.get("/api/v1/teams/{tid}")
def team_detail(tid: UUID, user: CurrentUser, db: Db):
    x = db.get(Team, tid)
    if not x: raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    require_class(db, user, x.class_id); out = team_json(db, x, user)
    own_team = membership(db, x.class_id, user.id) if user.role == "STUDENT" else None
    if own_team and own_team[1].id != x.id:
        raise ApiError(403, "TEAM_ACCESS_DENIED", "只能查看本组信息")
    if user.role == "TEACHER" or own_team:
        rows = db.execute(select(TeamMember, User).join(User).where(TeamMember.team_id == tid, TeamMember.status == "ACTIVE")).all(); out["members"] = [{"id": str(p.id), "name": p.display_name, "student_no": p.login_name, "role": m.role} for m, p in rows]
    return out


@app.post("/api/v1/teams/{tid}/applications", status_code=201)
def apply_team(tid: UUID, user: CsrfUser, db: Db):
    x = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not x or not x.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组暂不接受申请")
    course = require_writable_class(db, user, x.class_id); require_team_window(course, user)
    if membership(db, x.class_id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
    if db.scalar(select(TeamRequest).where(TeamRequest.team_id == tid, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING")): raise ApiError(409, "APPLICATION_EXISTS", "已提交过申请")
    req = TeamRequest(class_id=x.class_id, team_id=tid, applicant_id=user.id); db.add(req); notify(db, x.leader_id, "TEAM_APPLICATION", f"{user.display_name} 申请加入小组"); db.commit(); return {"id": str(req.id), "status": req.status}


@app.post("/api/v1/teams/{tid}/close-recruitment")
def close_team_recruitment(tid: UUID, user: CsrfUser, db: Db):
    return set_team_recruitment(tid, False, user, db)


@app.post("/api/v1/teams/{tid}/open-recruitment")
def open_team_recruitment(tid: UUID, user: CsrfUser, db: Db):
    return set_team_recruitment(tid, True, user, db)


def set_team_recruitment(tid: UUID, open_recruitment: bool, user: User, db: Session):
    team = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not team or team.status != "ACTIVE": raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    if user.role != "STUDENT" or team.leader_id != user.id:
        raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可修改招募状态")
    course = require_writable_class(db, user, team.class_id)
    if open_recruitment: require_team_window(course, user)
    if not open_recruitment:
        db.execute(TeamRequest.__table__.update().where(TeamRequest.team_id == tid, TeamRequest.status == "PENDING").values(status="CANCELLED", resolved_at=now()))
    if team.open_recruitment != open_recruitment:
        team.open_recruitment = open_recruitment
        team.version += 1
        audit(db, user, "TEAM_RECRUITMENT_OPENED" if open_recruitment else "TEAM_RECRUITMENT_CLOSED", "team", str(tid))
    db.commit()
    return team_json(db, team, user)


@app.get("/api/v1/team-requests")
def requests(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id); q = select(TeamRequest, Team, User).join(Team, Team.id == TeamRequest.team_id).join(User, User.id == TeamRequest.applicant_id).where(TeamRequest.class_id == class_id)
    if user.role == "STUDENT": q = q.where(or_(TeamRequest.applicant_id == user.id, Team.leader_id == user.id))
    rows = db.execute(q.order_by(TeamRequest.created_at.desc())).all()
    items = [{"id": str(r.id), "team_id": str(t.id), "team_name": t.name, "applicant_id": str(p.id), "applicant_name": p.display_name, "kind": r.kind, "status": r.status, "is_incoming": t.leader_id == user.id, "created_at": r.created_at} for r, t, p in rows]
    if user.role == "STUDENT":
        memberships = db.execute(select(TeamMember, Team).join(Team, Team.id == TeamMember.team_id).where(TeamMember.class_id == class_id, TeamMember.user_id == user.id, TeamMember.status == "LEFT")).all()
        items.extend({"id": str(member.id), "team_id": str(team.id), "team_name": team.name, "applicant_id": str(user.id), "applicant_name": user.display_name, "kind": "MEMBERSHIP", "status": member.status, "is_incoming": False, "created_at": member.joined_at} for member, team in memberships)
        items.sort(key=lambda item: item["created_at"].timestamp() if item["created_at"] else 0, reverse=True)
    return {"items": items}


@app.post("/api/v1/team-requests/{rid}/decision")
def request_decision(rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    req = db.scalar(select(TeamRequest).where(TeamRequest.id == rid).with_for_update()); x = db.scalar(select(Team).where(Team.id == req.team_id).with_for_update()) if req else None
    if not req or req.status != "PENDING": raise ApiError(409, "REQUEST_NOT_PENDING", "申请已处理")
    if not x or x.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可处理申请")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    if decision == "APPROVED":
        if x.status != "ACTIVE" or not x.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组已截止招募，不能加入")
        if membership(db, req.class_id, req.applicant_id): raise ApiError(409, "ALREADY_IN_TEAM", "申请人已加入其他小组")
        db.add(TeamMember(team_id=x.id, class_id=req.class_id, user_id=req.applicant_id)); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == req.class_id, TeamRequest.applicant_id == req.applicant_id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); req.status = "APPROVED"; notify(db, req.applicant_id, "TEAM_JOINED", f"已加入小组「{x.name}」")
    else: req.status, req.resolved_at = "REJECTED", now(); notify(db, req.applicant_id, "TEAM_REJECTED", f"加入「{x.name}」的申请未通过")
    audit(db, user, "TEAM_REQUEST_DECIDED", "team_request", str(req.id), {"decision": decision}); db.commit(); return {"id": str(req.id), "status": req.status}


@app.delete("/api/v1/team-requests/{rid}", status_code=204)
def cancel_request(rid: UUID, user: CsrfUser, db: Db):
    req = db.get(TeamRequest, rid)
    can_cancel = req and (req.applicant_id == user.id or (req.kind == "INVITATION" and req.inviter_id == user.id))
    if not can_cancel or req.status != "PENDING": raise ApiError(409, "REQUEST_NOT_CANCELLABLE", "申请或邀请无法取消")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    req.status, req.resolved_at = "CANCELLED", now(); audit(db, user, "TEAM_REQUEST_CANCELLED", "team_request", str(req.id)); db.commit(); return Response(status_code=204)


@app.post("/api/v1/teams/{tid}/topic")
def topic(tid: UUID, data: TopicIn, user: CsrfUser, db: Db):
    x = db.get(Team, tid)
    if not x or x.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可提交选题")
    require_writable_class(db, user, x.class_id)
    norm = "".join(data.name.casefold().split()); item = db.scalar(select(Topic).where(Topic.team_id == tid))
    if item: item.name, item.normalized_name, item.description, item.review_status, item.version = data.name.strip(), norm, data.description, "PENDING", item.version + 1
    else: item = Topic(class_id=x.class_id, team_id=tid, name=data.name.strip(), normalized_name=norm, description=data.description); db.add(item)
    try:
        db.flush()
        db.execute(Notification.__table__.delete().where(Notification.user_id == user.id, Notification.kind == "TOPIC_REQUIRED", Notification.object_type == "team", Notification.object_id == str(tid)))
        audit(db, user, "TOPIC_SUBMITTED", "team", str(tid)); db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "TOPIC_DUPLICATE", "该选题已被使用，请重新填写")
    return {"id": str(item.id), "name": item.name, "status": item.review_status}


def assignment_json(x: Assignment): return {"id": str(x.id), "class_id": str(x.class_id), "title": x.title, "description": render_description(x.description), "submitter_type": x.submitter_type, "starts_at": x.starts_at, "due_at": x.due_at, "allow_late": x.allow_late, "auto_review_enabled": x.auto_review_enabled, "auto_review_mode": x.auto_review_mode, "auto_review_criteria_text": x.auto_review_criteria_text or "", "auto_review_due_at": x.auto_review_due_at, "auto_review_status": x.auto_review_status, "auto_review_error": x.auto_review_error, "status": x.status, "version": x.version}


def assignment_progress_json(db: Session, assignment: Assignment) -> dict:
    """Return the teacher-facing workflow counters shown on the assignment list."""
    if assignment.submitter_type == "INDIVIDUAL":
        owner_ids = set(db.scalars(select(ClassMember.user_id).where(
            ClassMember.class_id == assignment.class_id,
            ClassMember.status == "ACTIVE",
            ClassMember.role == "STUDENT",
        )).all())
    else:
        owner_ids = set(db.scalars(select(Team.id).where(
            Team.class_id == assignment.class_id,
            Team.status == "ACTIVE",
        )).all())

    expected_count = len(owner_ids)
    submissions = [item for item in db.scalars(select(Submission).where(
        Submission.assignment_id == assignment.id,
    )).all() if (item.owner_user_id or item.owner_team_id) in owner_ids]
    submitted = [item for item in submissions if item.status == "SUBMITTED" and item.current_version_no]
    submitted_count = len(submitted)

    latest_versions = []
    if submitted:
        version_rows = db.scalars(select(SubmissionVersion).where(
            SubmissionVersion.submission_id.in_([item.id for item in submitted]),
        )).all()
        latest_by_submission = {}
        for version in version_rows:
            current = latest_by_submission.get(version.submission_id)
            if current is None or version.version_no > current.version_no:
                latest_by_submission[version.submission_id] = version
        latest_versions = list(latest_by_submission.values())

    teacher_graded_count = 0
    peer_review_version_ids = set()
    if latest_versions:
        assessments = db.scalars(select(SubmissionAssessment).where(
            SubmissionAssessment.submission_version_id.in_([item.id for item in latest_versions]),
            SubmissionAssessment.status == "PUBLISHED",
        )).all()
        teacher_version_ids = {item.submission_version_id for item in assessments if item.kind == "TEACHER"}
        peer_review_version_ids = {item.submission_version_id for item in assessments if item.kind == "PEER"}
        teacher_graded_count = sum(item.id in teacher_version_ids for item in latest_versions)

    campaign = assignment_review_campaign(db, assignment.id)
    direct_peer_review_count = len(peer_review_version_ids)
    review_enabled = assignment.submitter_type == "INDIVIDUAL" or campaign is not None
    review_assigned_count = 0
    review_completed_count = direct_peer_review_count
    if campaign:
        allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == campaign.id)).all()
        active_allocations = [item for item in allocations if item.status != "SKIPPED"]
        review_assigned_count = len(active_allocations)
        review_completed_count = sum(item.status == "COMPLETED" for item in active_allocations)
        if not review_completed_count:
            review_completed_count = db.scalar(select(func.count(PeerReview.id)).where(
                PeerReview.campaign_id == campaign.id,
                PeerReview.status == "VALID",
            )) or 0
    elif review_enabled:
        # Direct student peer reviews have no campaign/allocation rows. In that
        # mode each submitted work is one review target, so the denominator is
        # the current submitted count.
        review_assigned_count = submitted_count

    if expected_count == 0:
        completion_status = "NO_ROSTER"
    elif submitted_count < expected_count:
        completion_status = "PENDING_SUBMISSION"
    elif review_enabled and review_assigned_count and review_completed_count < review_assigned_count:
        completion_status = "PENDING_REVIEW"
    elif teacher_graded_count < submitted_count:
        completion_status = "PENDING_TEACHER_GRADING"
    else:
        completion_status = "COMPLETED"

    return {
        "expected_count": expected_count,
        "submitted_count": submitted_count,
        "teacher_graded_count": teacher_graded_count,
        "review_enabled": review_enabled,
        "review_assigned_count": review_assigned_count,
        "review_completed_count": review_completed_count,
        "completion_status": completion_status,
    }


def assignment_review_campaign(db: Session, assignment_id: UUID) -> ReviewCampaign | None:
    return db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment_id))


def review_config_editable(db: Session, assignment: Assignment) -> bool:
    return assignment.status != "CLOSED" and assignment.due_at > now() and assignment_review_campaign(db, assignment.id) is None


def has_review_criteria_file(db: Session, assignment_id: UUID) -> bool:
    return bool(db.scalar(select(FileObject.id).where(FileObject.assignment_id == assignment_id, FileObject.purpose == "REVIEW_CRITERIA", FileObject.active == True).limit(1)))  # noqa: E712


def file_json(file: FileObject, owner_name: str | None = None, submitted: bool = False) -> dict:
    suffix = Path(file.original_name).suffix.lower()
    render_type = "RICH_TEXT" if suffix == ".md" else "DOWNLOAD_ONLY"
    previewable = render_type != "DOWNLOAD_ONLY"
    return {"id": str(file.id), "name": file.original_name, "size": file.size_bytes, "render_type": render_type, "preview_status": file.preview_status, "preview_error": file.preview_error, "previewable": previewable, "download_only": not previewable, "purpose": file.purpose, "material_type": file.material_type, "owner_name": owner_name, "created_at": file.created_at, "submitted": submitted}


def writable_teacher_classes(db: Session, user: User, class_ids: list[UUID]) -> list[TeachingClass]:
    teacher(user)
    if len(set(class_ids)) != len(class_ids): raise ApiError(422, "DUPLICATE_CLASS", "教学班不能重复选择")
    courses = db.scalars(select(TeachingClass).where(TeachingClass.id.in_(class_ids), TeachingClass.teacher_id == user.id).with_for_update()).all()
    by_id = {x.id: x for x in courses}
    if len(by_id) != len(class_ids): raise ApiError(404, "CLASS_NOT_FOUND", "部分教学班不存在或无权访问")
    archived = [str(cid) for cid in class_ids if by_id[cid].status != "ACTIVE"]
    if archived: raise ApiError(409, "CLASS_ARCHIVED", "所选教学班中包含已归档班级", {"class_ids": archived})
    return [by_id[cid] for cid in class_ids]


def create_assignments_for_classes(data: AssignmentFields, courses: list[TeachingClass], user: User, db: Session) -> list[Assignment]:
    if data.starts_at and data.starts_at >= data.due_at:
        raise ApiError(422, "ASSIGNMENT_TIME_INVALID", "开始时间必须早于截止时间")
    if data.publish and data.submitter_type == "TEAM" and data.due_at <= now():
        raise ApiError(422, "TEAM_ASSIGNMENT_DUE_INVALID", "小组作业截止时间必须晚于当前时间")
    if data.auto_review_enabled:
        if data.submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "自动互评只能关联个人作业")
        if not data.auto_review_mode or not data.auto_review_due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_REQUIRED", "请完整配置自动互评模式和截止时间")
        if data.auto_review_due_at <= data.due_at: raise ApiError(422, "AUTO_REVIEW_TIME_INVALID", "互评截止时间必须晚于作业截止时间")
        if data.publish and not data.auto_review_criteria_text.strip(): raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "直接发布时必须填写自动互评标准文字")
    created = []
    for course in courses:
        item = Assignment(class_id=course.id, title=data.title.strip(), description=clean_html(data.description), submitter_type=data.submitter_type, starts_at=data.starts_at, due_at=data.due_at, allow_late=data.allow_late, auto_review_enabled=data.auto_review_enabled, auto_review_mode=data.auto_review_mode if data.auto_review_enabled else None, auto_review_criteria_text=data.auto_review_criteria_text.strip() if data.auto_review_enabled else None, auto_review_due_at=data.auto_review_due_at if data.auto_review_enabled else None, auto_review_status="PENDING" if data.auto_review_enabled else None, status="PUBLISHED" if data.publish else "DRAFT")
        db.add(item); db.flush(); created.append(item)
        if item.status == "PUBLISHED":
            for member in db.scalars(select(ClassMember).where(ClassMember.class_id == course.id, ClassMember.status == "ACTIVE")): notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"新作业：{item.title}")
        audit(db, user, "ASSIGNMENT_CREATED", "assignment", str(item.id), {"class_id": str(course.id)})
    return created


@app.get("/api/v1/assignments")
def assignments(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    team = require_team(db, class_id, user)[1] if user.role == "STUDENT" else None
    q = select(Assignment).where(Assignment.class_id == class_id)
    if user.role == "STUDENT":
        q = q.where(
            Assignment.status.in_(["PUBLISHED", "CLOSED"]),
            or_(Assignment.starts_at.is_(None), Assignment.starts_at <= now()),
        )
    items = db.scalars(q.order_by(Assignment.created_at.desc())).all()
    submissions_by_assignment = {}
    pending_teacher_reviews = {}
    if user.role == "STUDENT" and items:
        assignment_ids = [item.id for item in items]
        ownership = or_(Submission.owner_user_id == user.id, Submission.owner_team_id == team.id)
        submissions_by_assignment = {
            submission.assignment_id: submission
            for submission in db.scalars(
                select(Submission).where(Submission.assignment_id.in_(assignment_ids), ownership)
            ).all()
        }
    elif user.role == "TEACHER" and items:
        assignment_ids = [item.id for item in items]
        pending_teacher_reviews = dict(db.execute(
            select(Submission.assignment_id, func.count(SubmissionVersion.id))
            .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
            .where(
                Submission.assignment_id.in_(assignment_ids),
                Submission.status == "SUBMITTED",
                ~select(SubmissionAssessment.id).where(
                    SubmissionAssessment.submission_version_id == SubmissionVersion.id,
                    SubmissionAssessment.kind == "TEACHER",
                    SubmissionAssessment.status == "PUBLISHED",
                ).exists(),
            )
            .group_by(Submission.assignment_id)
        ).all())
    result = []
    for item in items:
        payload = assignment_json(item)
        if user.role == "STUDENT":
            submission = submissions_by_assignment.get(item.id)
            payload["submission_status"] = submission.status if submission else "NOT_SUBMITTED"
        else:
            payload["progress"] = assignment_progress_json(db, item)
            payload["pending_teacher_review_count"] = pending_teacher_reviews.get(item.id, 0)
        result.append(payload)
    return {"items": result, "total": len(result)}


@app.post("/api/v1/assignments", status_code=201)
def create_assignment(data: AssignmentIn, user: CsrfUser, db: Db):
    courses = writable_teacher_classes(db, user, [data.class_id])
    item = create_assignments_for_classes(data, courses, user, db)[0]
    db.commit(); return assignment_json(item)


@app.post("/api/v1/assignments/bulk", status_code=201)
def create_assignments_bulk(data: AssignmentBulkIn, user: CsrfUser, db: Db):
    courses = writable_teacher_classes(db, user, data.class_ids)
    items = create_assignments_for_classes(data, courses, user, db)
    db.commit(); return {"items": [assignment_json(x) for x in items], "total": len(items)}


@app.patch("/api/v1/assignments/{aid}")
def update_assignment(aid: UUID, data: AssignmentUpdateIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.version != data.version: raise ApiError(409, "ASSIGNMENT_VERSION_CONFLICT", "作业已被修改，请刷新后重试", {"current_version": assignment.version})
    has_submissions = bool(db.scalar(select(Submission.id).where(Submission.assignment_id == aid).limit(1)))
    if data.submitter_type and data.submitter_type != assignment.submitter_type and has_submissions: raise ApiError(409, "SUBMITTER_TYPE_LOCKED", "已有提交后不能修改提交类型")
    starts_at = data.starts_at if data.starts_at is not None else assignment.starts_at
    due_at = data.due_at if data.due_at is not None else assignment.due_at
    if starts_at and starts_at >= due_at: raise ApiError(422, "ASSIGNMENT_TIME_INVALID", "开始时间必须早于截止时间")

    review_fields = {"auto_review_enabled", "auto_review_mode", "auto_review_criteria_text", "auto_review_due_at"}
    changing_review_config = bool(review_fields & data.model_fields_set)
    campaign = assignment_review_campaign(db, aid)
    previous_class_id = assignment.class_id
    changing_class = data.class_id is not None and data.class_id != previous_class_id
    if changing_class:
        writable_teacher_classes(db, user, [data.class_id])
        if has_submissions or campaign:
            raise ApiError(409, "ASSIGNMENT_CLASS_LOCKED", "已有提交记录或互评活动，不能修改教学班")
    if changing_review_config and (assignment.status == "CLOSED" or assignment.due_at <= now() or campaign):
        raise ApiError(409, "AUTO_REVIEW_CONFIG_LOCKED", "作业已截止或互评活动已创建，不能修改互评配置")

    auto_review_enabled = data.auto_review_enabled if "auto_review_enabled" in data.model_fields_set else assignment.auto_review_enabled
    auto_review_mode = data.auto_review_mode if "auto_review_mode" in data.model_fields_set else assignment.auto_review_mode
    auto_review_criteria_text = data.auto_review_criteria_text if "auto_review_criteria_text" in data.model_fields_set else assignment.auto_review_criteria_text
    auto_review_due_at = data.auto_review_due_at if "auto_review_due_at" in data.model_fields_set else assignment.auto_review_due_at
    submitter_type = data.submitter_type or assignment.submitter_type
    if assignment.status == "PUBLISHED" and submitter_type == "TEAM" and due_at <= now():
        raise ApiError(422, "TEAM_ASSIGNMENT_DUE_INVALID", "小组作业截止时间必须晚于当前时间")
    if auto_review_enabled and campaign is None:
        if submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "自动互评只能关联个人作业")
        if not auto_review_mode or not auto_review_due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_REQUIRED", "请完整配置自动互评模式和截止时间")
        if auto_review_due_at <= due_at: raise ApiError(422, "AUTO_REVIEW_TIME_INVALID", "互评截止时间必须晚于作业截止时间")
        if not (auto_review_criteria_text or "").strip() and not has_review_criteria_file(db, aid):
            raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "互评标准文字和附件至少提供一种")
    for key in ("title", "description", "starts_at", "due_at", "allow_late", "submitter_type"):
        value = getattr(data, key)
        if value is not None:
            if key == "description": value = clean_html(value)
            setattr(assignment, key, value.strip() if isinstance(value, str) else value)
    if changing_review_config:
        assignment.auto_review_enabled = bool(auto_review_enabled)
        assignment.auto_review_mode = auto_review_mode if auto_review_enabled else None
        assignment.auto_review_criteria_text = (auto_review_criteria_text or "").strip() if auto_review_enabled else None
        assignment.auto_review_due_at = auto_review_due_at if auto_review_enabled else None
        assignment.auto_review_status = "PENDING" if auto_review_enabled else None
        assignment.auto_review_error = None
    if changing_class:
        assignment.class_id = data.class_id
        publish_event(db, class_id=previous_class_id, scopes=realtime_scopes("ASSIGNMENT_UPDATED"), resource_type="assignment", resource_id=str(aid), source_client_id=request_client_id.get())
        if assignment.status == "PUBLISHED":
            for member in db.scalars(select(ClassMember).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE")):
                notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"新作业：{assignment.title}")
    changes = {"previous_class_id": str(previous_class_id), "class_id": str(assignment.class_id)} if changing_class else None
    assignment.version += 1; audit(db, user, "ASSIGNMENT_UPDATED", "assignment", str(aid), changes); db.commit(); return assignment_json(assignment)


@app.post("/api/v1/assignments/{aid}/publish")
def publish_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    republishing = assignment.status in {"PUBLISHED", "CLOSED"}
    if assignment.status == "CLOSED" and assignment.due_at <= now():
        raise ApiError(422, "ASSIGNMENT_DUE_INVALID", "重新发布已截止作业前，请将截止时间设置为未来时间")
    if assignment.submitter_type == "TEAM" and assignment.due_at <= now():
        raise ApiError(422, "TEAM_ASSIGNMENT_DUE_INVALID", "小组作业截止时间必须晚于当前时间")
    if assignment.auto_review_enabled:
        criteria_exists = bool(db.scalar(select(FileObject.id).where(FileObject.assignment_id == aid, FileObject.purpose == "REVIEW_CRITERIA").limit(1)))
        if not (assignment.auto_review_criteria_text or "").strip() and not criteria_exists: raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "自动互评标准文字和附件至少提供一种")
        if assignment.submitter_type != "INDIVIDUAL" or not assignment.auto_review_mode or not assignment.auto_review_due_at or assignment.auto_review_due_at <= assignment.due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_INVALID", "自动互评配置不完整")
    assignment.status = "PUBLISHED"; assignment.version += 1
    for member in db.scalars(select(ClassMember).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE")): notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"{'作业已更新' if republishing else '新作业'}：{assignment.title}")
    audit(db, user, "ASSIGNMENT_PUBLISHED", "assignment", str(aid)); db.commit(); return assignment_json(assignment)


@app.post("/api/v1/assignments/{aid}/retract")
def retract_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status == "DRAFT": return assignment_json(assignment)
    if assignment.status not in {"PUBLISHED", "CLOSED"}: raise ApiError(409, "ASSIGNMENT_RETRACT_INVALID", "当前作业状态不能撤回发布")
    previous_status = assignment.status
    assignment.status = "DRAFT"
    assignment.version += 1
    audit(db, user, "ASSIGNMENT_RETRACTED", "assignment", str(aid), {"from": previous_status, "to": "DRAFT"})
    db.commit()
    return assignment_json(assignment)


@app.post("/api/v1/assignments/{aid}/close")
def close_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status == "CLOSED": return assignment_json(assignment)
    if assignment.status != "PUBLISHED": raise ApiError(409, "ASSIGNMENT_NOT_PUBLISHED", "只有已发布的作业可以提前截止")
    assignment.status = "CLOSED"
    assignment.due_at = now()
    assignment.version += 1
    audit(db, user, "ASSIGNMENT_CLOSED", "assignment", str(aid), {"due_at": assignment.due_at.isoformat()})
    db.commit()
    return assignment_json(assignment)


@app.delete("/api/v1/assignments/{aid}", status_code=204)
def delete_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    keys = [item.storage_path for item in db.scalars(select(FileObject).where(FileObject.assignment_id == aid)).all()]
    title = assignment.title
    audit(db, user, "ASSIGNMENT_DELETED", "assignment", str(aid), {"title": title})
    submission_ids = select(Submission.id).where(Submission.assignment_id == aid)
    version_ids = select(SubmissionVersion.id).where(SubmissionVersion.submission_id.in_(submission_ids))
    assessment_ids = select(SubmissionAssessment.id).where(SubmissionAssessment.assignment_id == aid)
    campaign_ids = select(ReviewCampaign.id).where(ReviewCampaign.assignment_id == aid)
    grade_ids = select(Grade.id).where(Grade.assignment_id == aid)
    db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id.in_(assessment_ids)))
    db.execute(delete(GradeRevision).where(GradeRevision.grade_id.in_(grade_ids)))
    db.execute(delete(Grade).where(Grade.assignment_id == aid))
    db.execute(delete(PeerReview).where(PeerReview.campaign_id.in_(campaign_ids)))
    db.execute(delete(ReviewAssignment).where(ReviewAssignment.campaign_id.in_(campaign_ids)))
    db.execute(delete(SubmissionAssessment).where(SubmissionAssessment.assignment_id == aid))
    db.execute(delete(VersionFile).where(VersionFile.version_id.in_(version_ids)))
    db.execute(delete(SubmissionVersion).where(SubmissionVersion.submission_id.in_(submission_ids)))
    db.execute(delete(Submission).where(Submission.assignment_id == aid))
    db.execute(delete(GradeCoefficient).where(GradeCoefficient.assignment_id == aid))
    db.execute(delete(ReviewCampaign).where(ReviewCampaign.assignment_id == aid))
    db.execute(delete(FileObject).where(FileObject.assignment_id == aid))
    db.delete(assignment)
    db.commit()
    for key in keys:
        storage.delete_object(key)
    return Response(status_code=204)


def own_submission(db: Session, a: Assignment, user: User):
    if a.submitter_type == "INDIVIDUAL": return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == user.id)), None
    _, x = require_team(db, a.class_id, user); return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_team_id == x.id)), x


def workspace_scope(db: Session, assignment: Assignment, user: User) -> tuple[UUID | None, UUID | None, Team | None]:
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可编辑作业草稿")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status != "PUBLISHED": raise ApiError(409, "ASSIGNMENT_NOT_WRITABLE", "作业当前不可编辑")
    if assignment.starts_at and assignment.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
    if assignment.due_at < now() and not assignment.allow_late: raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续编辑")
    if assignment.submitter_type == "INDIVIDUAL": return user.id, None, None
    _, team = require_team(db, assignment.class_id, user)
    return None, team.id, team


def document_is_criteria(db: Session, item: SubmissionDocument) -> bool:
    source = db.get(FileObject, item.source_file_id) if item.source_file_id else None
    return bool(source and source.material_type == "CRITERIA")


def document_json(db: Session, item: SubmissionDocument, locked: bool = False, editor_name: str | None = None) -> dict:
    if editor_name is None:
        editor = db.get(User, item.updated_by)
        editor_name = editor.display_name if editor else ""
    return {"id": str(item.id), "name": item.name, "sort_order": item.sort_order, "revision": item.revision, "updated_at": item.updated_at.isoformat() if item.updated_at else None, "updated_by": editor_name, "locked": locked}


def document_content_json(db: Session, item: SubmissionDocument, locked: bool = False) -> dict:
    result = document_json(db, item, locked)
    result["markdown_content"] = "" if locked else item.markdown_content
    return result


def workspace_json(db: Session, workspace: SubmissionWorkspace, user: User) -> dict:
    rows = db.execute(
        select(SubmissionDocument, User.display_name)
        .outerjoin(User, User.id == SubmissionDocument.updated_by)
        .options(load_only(SubmissionDocument.id, SubmissionDocument.name, SubmissionDocument.sort_order, SubmissionDocument.revision, SubmissionDocument.updated_at, SubmissionDocument.updated_by, SubmissionDocument.source_file_id, SubmissionDocument.created_at))
        .where(SubmissionDocument.workspace_id == workspace.id)
        .order_by(SubmissionDocument.sort_order, SubmissionDocument.created_at)
    ).all()
    return {"id": str(workspace.id), "documents": [document_json(db, item, False, editor_name or "") for item, editor_name in rows], "updated_at": workspace.updated_at}


def check_source_images(db: Session, workspace: SubmissionWorkspace, document: SubmissionDocument, user: User) -> bool:
    if document.source_images_checked_at is not None:
        return False
    source_file = db.get(FileObject, document.source_file_id) if document.source_file_id else None
    if not source_file:
        source_file = db.scalar(
            select(FileObject)
            .where(
                FileObject.assignment_id == workspace.assignment_id,
                FileObject.purpose == "ATTACHMENT",
                FileObject.active == True,  # noqa: E712
                or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"),
                func.lower(FileObject.original_name) == document.name.lower(),
            )
            .order_by(FileObject.created_at.desc())
            .limit(1)
        )
    if not source_file:
        document.source_images_checked_at = now()
        return True
    try:
        source = decode_text_file(storage.get_object_bytes(source_file.storage_path))
    except (OssError, UnicodeDecodeError):
        return False
    corrupted_text = "???" in document.name or document.markdown_content.count("?") >= 5
    restored = source if corrupted_text or not document.markdown_content.strip() else restore_embedded_tables(source, restore_embedded_images(source, document.markdown_content))
    changed = restored != document.markdown_content or document.name != Path(source_file.original_name).name or document.source_file_id != source_file.id
    document.source_file_id = source_file.id
    document.name = Path(source_file.original_name).name
    document.markdown_content = restored
    document.source_images_checked_at = now()
    if changed:
        document.revision += 1
        document.updated_by = user.id
    return True


def remove_criteria_workspace_documents(db: Session, workspace: SubmissionWorkspace) -> bool:
    documents = db.scalars(select(SubmissionDocument).join(FileObject, FileObject.id == SubmissionDocument.source_file_id).where(SubmissionDocument.workspace_id == workspace.id, FileObject.material_type == "CRITERIA")).all()
    for document in documents:
        db.delete(document)
    return bool(documents)


def restore_embedded_images(template: str, draft: str) -> str:
    image_pattern = re.compile(
        r"!\[[^\]\r\n]*\]\(data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+\)"
        r"|<img\b[^>]*\bsrc\s*=\s*([\"'])data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+\1[^>]*>",
        re.IGNORECASE,
    )
    data_url_pattern = re.compile(r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+", re.IGNORECASE)
    result = draft
    for match in image_pattern.finditer(template):
        image_markdown = match.group(0)
        data_url = data_url_pattern.search(image_markdown)
        if data_url and data_url.group(0) in result: continue
        prefix_lines = [line for line in template[:match.start()].splitlines() if line.strip()]
        anchor = next((line for line in reversed(prefix_lines) if line in result), None)
        if anchor:
            position = result.find(anchor) + len(anchor)
            result = f"{result[:position]}\n\n{image_markdown}{result[position:]}"
        else:
            result = f"{image_markdown}\n\n{result}"
    return result


def markdown_table_blocks(value: str) -> list[tuple[str, list[list[str]]]]:
    def cells(line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"): stripped = stripped[1:]
        if stripped.endswith("|"): stripped = stripped[:-1]
        return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]

    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tables = []
    index = 0
    while index + 1 < len(lines):
        header = cells(lines[index])
        separator = cells(lines[index + 1])
        valid_separator = len(header) >= 2 and len(separator) == len(header) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
        if "|" not in lines[index] or not valid_separator:
            index += 1
            continue
        end = index + 2
        rows = [header]
        while end < len(lines) and "|" in lines[end]:
            row = cells(lines[end])
            if len(row) != len(header): break
            rows.append(row)
            end += 1
        tables.append(("\n".join(lines[index:end]), rows))
        index = end
    return tables


def restore_embedded_tables(template: str, draft: str) -> str:
    result = draft.replace("\r\n", "\n").replace("\r", "\n")
    for table, rows in markdown_table_blocks(template):
        if table in result: continue
        flattened = "".join(cell for row in rows for cell in row)
        if flattened and result.count(flattened) == 1:
            result = result.replace(flattened, table, 1)
    return result


def require_workspace_document(db: Session, aid: UUID, document_id: UUID, user: User) -> tuple[Assignment, SubmissionWorkspace, SubmissionDocument, Team | None]:
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    owner_user_id, owner_team_id, team = workspace_scope(db, assignment, user)
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == owner_user_id)) if owner_user_id else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == owner_team_id))
    document = db.get(SubmissionDocument, document_id)
    if not workspace or not document or document.workspace_id != workspace.id: raise ApiError(404, "DOCUMENT_NOT_FOUND", "在线文档不存在")
    if document_is_criteria(db, document): raise ApiError(403, "CRITERIA_READ_ONLY", "判定标准仅供提交后查看，不能编辑")
    return assignment, workspace, document, team


@app.post("/api/v1/assignments/{aid}/workspace")
def initialize_workspace(aid: UUID, user: CsrfUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    owner_user_id, owner_team_id, _ = workspace_scope(db, assignment, user)
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == owner_user_id)) if owner_user_id else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == owner_team_id))
    if workspace:
        removed_criteria = remove_criteria_workspace_documents(db, workspace)
        if removed_criteria: db.commit()
        return workspace_json(db, workspace, user)
    workspace = SubmissionWorkspace(assignment_id=aid, owner_user_id=owner_user_id, owner_team_id=owner_team_id)
    db.add(workspace); db.flush()
    templates = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT", FileObject.active == True, or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"), FileObject.original_name.like("%.md")).order_by(FileObject.created_at)).all()  # noqa: E712
    used_names = set()
    for index, template in enumerate(templates):
        name = Path(template.original_name).name
        if name.casefold() in used_names:
            name = f"{Path(name).stem}-{index + 1}.md"
        used_names.add(name.casefold())
        db.add(SubmissionDocument(workspace_id=workspace.id, source_file_id=template.id, name=name, markdown_content="", source_images_checked_at=None, sort_order=index, updated_by=user.id))
    audit(db, user, "SUBMISSION_WORKSPACE_CREATED", "submission_workspace", str(workspace.id)); db.commit()
    return workspace_json(db, workspace, user)


@app.post("/api/v1/assignments/{aid}/workspace/documents", status_code=201)
def create_workspace_document(aid: UUID, data: SubmissionDocumentIn, user: CsrfUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    owner_user_id, owner_team_id, _ = workspace_scope(db, assignment, user)
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == owner_user_id)) if owner_user_id else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == owner_team_id))
    if not workspace: raise ApiError(409, "WORKSPACE_REQUIRED", "请先打开在线作业工作区")
    name = Path(data.name.strip()).name
    if not name.lower().endswith(".md"): name += ".md"
    if db.scalar(select(SubmissionDocument.id).where(SubmissionDocument.workspace_id == workspace.id, func.lower(SubmissionDocument.name) == name.lower())): raise ApiError(409, "DOCUMENT_NAME_EXISTS", "同名文档已经存在")
    order = db.scalar(select(func.max(SubmissionDocument.sort_order)).where(SubmissionDocument.workspace_id == workspace.id))
    item = SubmissionDocument(workspace_id=workspace.id, name=name, markdown_content="", source_images_checked_at=now(), sort_order=(order if order is not None else -1) + 1, updated_by=user.id)
    db.add(item); db.commit(); return document_json(db, item)


@app.get("/api/v1/assignments/{aid}/workspace/documents/{document_id}")
def get_workspace_document(aid: UUID, document_id: UUID, user: CurrentUser, db: Db):
    _, workspace, document, _ = require_workspace_document(db, aid, document_id, user)
    if check_source_images(db, workspace, document, user):
        db.commit()
    return document_content_json(db, document)


@app.put("/api/v1/assignments/{aid}/workspace/documents/{document_id}")
def update_workspace_document(aid: UUID, document_id: UUID, data: SubmissionDocumentUpdateIn, user: CsrfUser, db: Db):
    assignment, workspace, document, _ = require_workspace_document(db, aid, document_id, user)
    locked = db.scalar(select(SubmissionDocument).where(SubmissionDocument.id == document.id).with_for_update())
    if locked.revision != data.revision:
        raise ApiError(409, "DOCUMENT_VERSION_CONFLICT", f"{db.get(User, locked.updated_by).display_name} 已更新此文档，请刷新后继续", {"document": document_json(db, locked)})
    locked.markdown_content = data.markdown_content.replace("\x00", "")
    locked.revision += 1; locked.updated_by = user.id; workspace.updated_at = now()
    audience = [user.id] if workspace.owner_user_id else list(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == workspace.owner_team_id, TeamMember.status == "ACTIVE")))
    publish_event(
        db, class_id=assignment.class_id, scopes=["workspace"], resource_type="submission_document",
        resource_id=document.id, user_ids=audience, roles=["STUDENT"], source_client_id=request_client_id.get(),
        assignment_id=str(assignment.id), workspace_id=str(workspace.id), revision=locked.revision,
    )
    db.commit(); return document_json(db, locked)


@app.delete("/api/v1/assignments/{aid}/workspace/documents/{document_id}", status_code=204)
def delete_workspace_document(aid: UUID, document_id: UUID, user: CsrfUser, db: Db):
    _, workspace, document, _ = require_workspace_document(db, aid, document_id, user)
    if document.source_file_id: raise ApiError(403, "SOURCE_DOCUMENT_DELETE_FORBIDDEN", "教师提供的作业文档不能删除")
    count = db.scalar(select(func.count()).select_from(SubmissionDocument).where(SubmissionDocument.workspace_id == workspace.id)) or 0
    if count <= 1: raise ApiError(409, "LAST_DOCUMENT_REQUIRED", "作业至少需要保留一份 Markdown 文档")
    db.delete(document); db.commit(); return Response(status_code=204)


TEACHING_MATERIAL_SUFFIXES = {".md", ".html", ".htm", ".mp4"}
TEACHING_MATERIAL_MIME_TYPES = {
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".html": {"text/html", "text/plain", "application/octet-stream"},
    ".htm": {"text/html", "text/plain", "application/octet-stream"},
    ".mp4": {"video/mp4", "application/octet-stream"},
}


def teaching_material_folder_json(folder: TeachingMaterialFolder) -> dict:
    return {"id": str(folder.id), "parent_id": str(folder.parent_id) if folder.parent_id else None, "name": folder.name, "type": "folder"}


def teaching_material_json(material: TeachingMaterial) -> dict:
    return {
        "id": str(material.id), "folder_id": str(material.folder_id) if material.folder_id else None,
        "name": material.original_name, "type": "file", "media_type": material.media_type,
        "size": material.size_bytes, "mime": material.detected_mime,
        "content_url": f"/api/v1/teaching-materials/files/{material.id}/content",
        "created_at": material.created_at,
    }


def require_material_folder(db: Session, user: User, folder_id: UUID, class_id: UUID | None = None) -> TeachingMaterialFolder:
    folder = db.get(TeachingMaterialFolder, folder_id)
    if not folder or (class_id and folder.class_id != class_id):
        raise ApiError(404, "MATERIAL_FOLDER_NOT_FOUND", "鏂囦欢澶逛笉瀛樺湪")
    require_class(db, user, folder.class_id)
    return folder


@app.get("/api/v1/teaching-materials")
def teaching_materials(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    folders = db.scalars(select(TeachingMaterialFolder).where(TeachingMaterialFolder.class_id == class_id).order_by(TeachingMaterialFolder.name, TeachingMaterialFolder.created_at)).all()
    files = db.scalars(select(TeachingMaterial).where(TeachingMaterial.class_id == class_id, TeachingMaterial.active == True).order_by(TeachingMaterial.original_name, TeachingMaterial.created_at)).all()  # noqa: E712
    return {"class_id": str(class_id), "can_manage": user.role == "TEACHER", "folders": [teaching_material_folder_json(item) for item in folders], "files": [teaching_material_json(item) for item in files]}


@app.post("/api/v1/teaching-materials/folders", status_code=201)
def create_teaching_material_folder(data: TeachingMaterialFolderIn, user: CsrfUser, db: Db):
    teacher(user)
    require_writable_class(db, user, data.class_id)
    if data.parent_id:
        parent = require_material_folder(db, user, data.parent_id, data.class_id)
        if parent.class_id != data.class_id:
            raise ApiError(404, "MATERIAL_FOLDER_NOT_FOUND", "鐖剁骇鏂囦欢澶逛笉瀛樺湪")
    name = data.name.strip()
    if not name:
        raise ApiError(422, "MATERIAL_FOLDER_NAME_INVALID", "鏂囦欢澶瑰悕涓嶈兘涓虹┖")
    duplicate = db.scalar(select(TeachingMaterialFolder).where(TeachingMaterialFolder.class_id == data.class_id, TeachingMaterialFolder.parent_id == data.parent_id, TeachingMaterialFolder.name == name))
    if duplicate:
        raise ApiError(409, "MATERIAL_FOLDER_EXISTS", "鍚屼竴鐩綍涓嬪凡瀛樺湪鍚屽悕鏂囦欢澶�")
    folder = TeachingMaterialFolder(class_id=data.class_id, parent_id=data.parent_id, owner_id=user.id, name=name)
    db.add(folder); db.commit(); db.refresh(folder)
    return teaching_material_folder_json(folder)


@app.delete("/api/v1/teaching-materials/folders/{folder_id}", status_code=204)
def delete_teaching_material_folder(folder_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    folder = require_material_folder(db, user, folder_id)
    require_writable_class(db, user, folder.class_id)
    has_child_folder = db.scalar(select(TeachingMaterialFolder.id).where(TeachingMaterialFolder.parent_id == folder.id).limit(1))
    has_file = db.scalar(select(TeachingMaterial.id).where(TeachingMaterial.folder_id == folder.id, TeachingMaterial.active == True).limit(1))  # noqa: E712
    if has_child_folder or has_file:
        raise ApiError(409, "MATERIAL_FOLDER_NOT_EMPTY", "鏂囦欢澶归潪绌猴紝璇峰厛绉婚櫎鍐呭")
    db.delete(folder); db.commit()
    return Response(status_code=204)


@app.post("/api/v1/teaching-materials/files", status_code=201)
def upload_teaching_material(user: CsrfUser, db: Db, class_id: UUID = Query(), folder_id: UUID | None = Query(None), file: UploadFile = File(...)):
    teacher(user)
    require_writable_class(db, user, class_id)
    if folder_id:
        require_material_folder(db, user, folder_id, class_id)
    original_name = Path(file.filename or "file").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in TEACHING_MATERIAL_SUFFIXES:
        raise ApiError(422, "MATERIAL_FILE_TYPE_INVALID", "仅支持 Markdown、HTML 和 MP4 文件")
    if file.content_type and file.content_type not in TEACHING_MATERIAL_MIME_TYPES[suffix]:
        raise ApiError(422, "MATERIAL_FILE_MIME_INVALID", "文件 MIME 类型与扩展名不匹配")
    duplicate = db.scalar(select(TeachingMaterial).where(TeachingMaterial.class_id == class_id, TeachingMaterial.folder_id == folder_id, TeachingMaterial.original_name == original_name, TeachingMaterial.active == True))  # noqa: E712
    if duplicate:
        raise ApiError(409, "MATERIAL_FILE_EXISTS", "同一目录下已存在同名文件")
    material_id = uuid4()
    relative = f"teaching-materials/{class_id}/{material_id.hex}{suffix}"
    temporary = Path(tempfile.gettempdir()) / f"teaching-material-{material_id.hex}{suffix}"
    size = 0
    try:
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise ApiError(422, "FILE_SIZE_INVALID", "文件不能超过 500 MB")
                output.write(chunk)
        if not size:
            raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空")
        storage.put_object(relative, temporary)
    finally:
        file.file.close()
        temporary.unlink(missing_ok=True)
    media_type = "MARKDOWN" if suffix == ".md" else "HTML" if suffix in {".html", ".htm"} else "VIDEO"
    material = TeachingMaterial(class_id=class_id, folder_id=folder_id, owner_id=user.id, storage_path=relative, original_name=original_name, size_bytes=size, detected_mime=file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream", media_type=media_type)
    db.add(material); db.commit(); db.refresh(material)
    return teaching_material_json(material)


@app.delete("/api/v1/teaching-materials/files/{file_id}", status_code=204)
def delete_teaching_material(file_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    material = db.get(TeachingMaterial, file_id)
    if not material or not material.active:
        raise ApiError(404, "MATERIAL_FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, material.class_id)
    key = material.storage_path
    db.delete(material); db.commit()
    storage.delete_object(key)
    return Response(status_code=204)


@app.get("/api/v1/teaching-materials/files/{file_id}/content")
def teaching_material_content(file_id: UUID, user: CurrentUser, db: Db):
    material = db.get(TeachingMaterial, file_id)
    if not material or not material.active:
        raise ApiError(404, "MATERIAL_FILE_NOT_FOUND", "文件不存在")
    require_class(db, user, material.class_id)
    media_type = {"MARKDOWN": "text/markdown", "HTML": "text/html", "VIDEO": "video/mp4"}[material.media_type]
    return StreamingResponse(storage.get_object_stream(material.storage_path), media_type=media_type, headers={"Content-Disposition": content_disposition(material.original_name, "inline")})


@app.post("/api/v1/assignments/{aid}/files", status_code=201)
def upload(aid: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...), purpose: Literal["ATTACHMENT", "REVIEW_CRITERIA"] | None = Query(None), material_type: Literal["TASK", "ATTACHMENT", "CRITERIA"] | None = Query(None)):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, a.class_id)
    team = None
    selected_purpose = (purpose or "ATTACHMENT") if user.role == "TEACHER" else "SUBMISSION"
    selected_material_type = (material_type or "ATTACHMENT") if selected_purpose == "ATTACHMENT" else None
    if user.role == "TEACHER" and selected_purpose == "REVIEW_CRITERIA" and not review_config_editable(db, a):
        raise ApiError(409, "AUTO_REVIEW_CONFIG_LOCKED", "作业已截止或互评活动已创建，不能修改互评标准附件")
    if user.role == "STUDENT":
        if a.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续上传附件")
        if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
        if a.starts_at and a.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
        _, team = require_team(db, a.class_id, user)
    suffix = Path(file.filename or "file").suffix.lower()
    if selected_material_type == "CRITERIA" and suffix != ".md":
        raise ApiError(422, "CRITERIA_FILE_TYPE_INVALID", "判定标准仅支持 Markdown 文档")
    supported = STUDENT_UPLOAD_FILE_SUFFIXES if user.role == "STUDENT" else PREVIEWABLE_FILE_SUFFIXES | DOWNLOAD_ONLY_FILE_SUFFIXES
    if suffix not in supported:
        message = "学生提交仅支持 Markdown、HTML、PDF 和常见图片" if user.role == "STUDENT" else "仅支持 Markdown、HTML、PDF、常见图片、Office 文档和 ZIP/RAR/7Z 压缩包"
        raise ApiError(422, "FILE_TYPE_INVALID", message)
    expected_mimes = {
        ".md": {"text/markdown", "text/plain", "application/octet-stream"},
        ".html": {"text/html", "text/plain", "application/octet-stream"}, ".htm": {"text/html", "text/plain", "application/octet-stream"},
        ".pdf": {"application/pdf"},
        ".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"}, ".gif": {"image/gif"}, ".webp": {"image/webp"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        ".zip": {"application/zip", "application/x-zip-compressed"}, ".rar": {"application/vnd.rar", "application/x-rar-compressed"}, ".7z": {"application/x-7z-compressed"},
    }
    if suffix in expected_mimes and file.content_type and file.content_type not in expected_mimes[suffix]:
        raise ApiError(422, "FILE_MIME_INVALID", "文件 MIME 类型与扩展名不匹配")
    fid = uuid4(); relative = f"{aid}/{fid.hex}{suffix}"
    temporary = Path(tempfile.gettempdir()) / f"upload-{fid.hex}{suffix}"
    size = 0
    try:
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空且不得超过 500 MB")
                output.write(chunk)
        if not size: raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空")
        storage.put_object(relative, temporary)
    finally:
        file.file.close()
        temporary.unlink(missing_ok=True)
    team_id = team.id if team and a.submitter_type == "TEAM" else None
    preview_status = "READY" if suffix in PREVIEWABLE_FILE_SUFFIXES else "NOT_AVAILABLE"
    x = FileObject(id=fid, owner_id=user.id, assignment_id=aid, team_id=team_id, purpose=selected_purpose, material_type=selected_material_type, storage_path=relative, original_name=Path(file.filename or "file").name, size_bytes=size, detected_mime=file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream", preview_status=preview_status)
    db.add(x)
    db.commit()
    return file_json(x, user.display_name)


@app.get("/api/v1/assignments/{aid}/files")
def assignment_files(aid: UUID, user: CurrentUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    team = require_team(db, assignment.class_id, user)[1] if user.role == "STUDENT" else None
    submitted = False
    if user.role == "STUDENT":
        own, _ = own_submission(db, assignment, user)
        submitted = bool(own and own.status == "SUBMITTED")
    material_query = select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT")
    if user.role == "STUDENT" and not submitted:
        material_query = material_query.where(or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"))
    materials = db.scalars(material_query.order_by(FileObject.created_at)).all()
    criteria = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "REVIEW_CRITERIA").order_by(FileObject.created_at)).all()
    drafts = []
    if user.role == "STUDENT":
        q = select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == True)  # noqa: E712
        q = q.where(FileObject.owner_id == user.id) if assignment.submitter_type == "INDIVIDUAL" else q.where(FileObject.team_id == team.id)
        drafts = db.scalars(q.order_by(FileObject.created_at)).all()
    owner_ids = {file.owner_id for file in [*materials, *criteria, *drafts]}
    owners = {owner.id: owner.display_name for owner in db.scalars(select(User).where(User.id.in_(owner_ids))).all()} if owner_ids else {}
    linked_file_ids = set(db.scalars(select(VersionFile.file_id).where(VersionFile.file_id.in_([file.id for file in drafts]))).all()) if drafts else set()
    def item(file: FileObject):
        return file_json(file, owners.get(file.owner_id, ""), file.id in linked_file_ids)
    return {"attachments": [item(x) for x in materials], "review_criteria": [item(x) for x in criteria], "drafts": [item(x) for x in drafts]}


@app.get("/api/v1/assignments/{aid}/materials.zip")
def download_assignment_materials(aid: UUID, user: CurrentUser, db: Db, file_ids: list[UUID] = Query(min_length=1, max_length=200)):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    if user.role == "STUDENT" and assignment.status not in {"PUBLISHED", "CLOSED"}:
        raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可查看的作业不存在")
    files = db.scalars(select(FileObject).where(
        FileObject.assignment_id == aid, FileObject.id.in_(file_ids),
        FileObject.purpose == "ATTACHMENT", FileObject.active == True,  # noqa: E712
    ).order_by(FileObject.created_at)).all()
    if len(files) != len(set(file_ids)):
        raise ApiError(422, "MATERIAL_FILE_INVALID", "部分文件不存在或不属于该作业资料")
    if user.role == "STUDENT" and any(file.material_type == "CRITERIA" for file in files):
        submission, _ = own_submission(db, assignment, user)
        if not submission or submission.status != "SUBMITTED":
            raise ApiError(403, "CRITERIA_REQUIRES_SUBMISSION", "提交作业后才能查看判定标准")
    archive = TemporaryFile()
    try:
        used_names = set()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for file in files:
                original = Path(file.original_name).name
                name, index = original, 1
                while name.casefold() in used_names:
                    name = f"{Path(original).stem} ({index}){Path(original).suffix}"
                    index += 1
                used_names.add(name.casefold())
                try:
                    with bundle.open(name, "w") as dest:
                        for chunk in storage.get_object_stream(file.storage_path):
                            dest.write(chunk)
                except NoSuchKey:
                    raise ApiError(404, "FILE_MISSING", "文件存储不可用")
        archive.seek(0)
    except Exception:
        archive.close()
        raise

    def chunks():
        try:
            while chunk := archive.read(1024 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(chunks(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="assignment-materials.zip"'})


@app.delete("/api/v1/files/{fid}", status_code=204)
def delete_file(fid: UUID, user: CsrfUser, db: Db):
    file = db.get(FileObject, fid); assignment = db.get(Assignment, file.assignment_id) if file else None
    if not file or not assignment: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, assignment.class_id)
    if file.owner_id != user.id: raise ApiError(403, "FILE_FORBIDDEN", "只能删除自己上传的文件")
    if file.purpose == "REVIEW_CRITERIA":
        if not review_config_editable(db, assignment):
            raise ApiError(409, "AUTO_REVIEW_CONFIG_LOCKED", "作业已截止或互评活动已创建，不能修改互评标准附件")
        remaining = db.scalar(select(func.count()).select_from(FileObject).where(FileObject.assignment_id == assignment.id, FileObject.purpose == "REVIEW_CRITERIA", FileObject.active == True, FileObject.id != fid)) or 0  # noqa: E712
        if assignment.auto_review_enabled and not (assignment.auto_review_criteria_text or "").strip() and remaining == 0:
            raise ApiError(409, "REVIEW_CRITERIA_REQUIRED", "启用互评时必须保留标准文字或至少一个附件")
    if db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == fid).limit(1)):
        file.active = False
        db.commit()
        return Response(status_code=204)
    key = file.storage_path; db.delete(file); db.commit()
    storage.delete_object(key)
    return Response(status_code=204)


@app.patch("/api/v1/files/{fid}")
def retype_file(fid: UUID, body: MaterialTypeIn, user: CsrfUser, db: Db):
    file = db.get(FileObject, fid); assignment = db.get(Assignment, file.assignment_id) if file else None
    if not file or not assignment: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, assignment.class_id)
    if file.owner_id != user.id: raise ApiError(403, "FILE_FORBIDDEN", "只能修改自己上传的文件")
    if file.purpose != "ATTACHMENT": raise ApiError(422, "FILE_TYPE_NOT_APPLICABLE", "只有作业资料附件可以分类")
    if body.material_type == "CRITERIA" and Path(file.original_name).suffix.lower() != ".md":
        raise ApiError(422, "CRITERIA_FILE_TYPE_INVALID", "判定标准仅支持 Markdown 文档")
    file.material_type = body.material_type
    db.commit()
    return file_json(file, user.display_name)


@app.get("/api/v1/assignments/{aid}/submission")
def submission(aid: UUID, user: CurrentUser, db: Db):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    s, _ = own_submission(db, a, user)
    latest = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s else None
    files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == latest.id)).all() if latest else []
    result = displayed_submission_grade_result(db, latest) if latest else {"final_grade": None, "grading_status": "PENDING_SUBMISSION"}
    return {"status": s.status if s else "EMPTY", "submitted_at": latest.submitted_at if latest else None, "is_late": latest.is_late if latest else False, "final_grade": result.get("final_grade"), "grading_status": result.get("grading_status"), "files": [file_json(file) for file in files]}


@app.post("/api/v1/assignments/{aid}/submission", status_code=201)
def submit(aid: UUID, user: CsrfUser, db: Db, idempotency_key: Annotated[str | None, Header()] = None):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    if a.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续提交")
    if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    require_writable_class(db, user, a.class_id)
    if a.starts_at and a.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
    team = None
    if a.submitter_type == "INDIVIDUAL":
        db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        s = db.scalar(select(Submission).where(Submission.assignment_id == aid, Submission.owner_user_id == user.id).with_for_update())
    else:
        _, team = require_team(db, a.class_id, user)
        db.scalar(select(Team.id).where(Team.id == team.id).with_for_update())
        s = db.scalar(select(Submission).where(Submission.assignment_id == aid, Submission.owner_team_id == team.id).with_for_update())
        if team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "小组作业仅组长可正式提交")
    current = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s and s.current_version_no else None
    assert_submission_update_allowed(db, s, current) if s else None
    can_update_low_grade = bool(current and submission_grade_result(db, current).get("final_grade") in {"C", "D", "E"})
    if a.due_at < now() and not a.allow_late and not can_update_low_grade:
        raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止且不允许迟交")
    file_scope = FileObject.owner_id == user.id if not team else FileObject.team_id == team.id
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == user.id)) if not team else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == team.id))
    if workspace:
        documents = [document for document in db.scalars(select(SubmissionDocument).where(SubmissionDocument.workspace_id == workspace.id).order_by(SubmissionDocument.sort_order, SubmissionDocument.created_at)).all() if not document_is_criteria(db, document)]
        if not documents: raise ApiError(422, "SUBMISSION_DOCUMENTS_REQUIRED", "在线作业中至少需要一份 Markdown 文档")
        for document in documents:
            check_source_images(db, workspace, document, user)
        empty = next((document for document in documents if not document.markdown_content.strip()), None)
        if empty: raise ApiError(422, "SUBMISSION_DOCUMENT_EMPTY", f"文档 {empty.name} 不能为空")
        db.execute(FileObject.__table__.update().where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == True, file_scope).values(active=False))  # noqa: E712
        for document in documents:
            content = document.markdown_content.encode("utf-8")
            fid = uuid4(); relative = f"{aid}/{fid.hex}.md"
            storage.put_bytes(relative, content)
            db.add(FileObject(id=fid, owner_id=user.id, assignment_id=aid, team_id=team.id if team else None, purpose="SUBMISSION", storage_path=relative, original_name=document.name, size_bytes=len(content), detected_mime="text/markdown", preview_status="READY"))
        db.flush()
    files = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == True, file_scope).order_by(FileObject.created_at)).all()  # noqa: E712
    if not files: raise ApiError(422, "SUBMISSION_FILES_REQUIRED", "请先上传作业附件")
    if not s: s = Submission(assignment_id=aid, owner_user_id=user.id if not team else None, owner_team_id=team.id if team else None); db.add(s); db.flush()
    if idempotency_key and current and current.idempotency_key == idempotency_key:
        return {"id": str(s.id), "submitted_at": current.submitted_at, "is_late": current.is_late}
    snapshot = {}
    if team:
        rows = db.execute(select(TeamMember, User).join(User).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE").order_by(User.login_name)).all()
        snapshot = {"members": [{"id": str(person.id), "student_no": person.login_name, "name": person.display_name, "role": member.role} for member, person in rows]}
    submitted_at = now()
    s.current_version_no = (current.version_no + 1) if current else 1
    was_peer_reviewed = bool(current and db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == current.id, SubmissionAssessment.kind == "PEER", SubmissionAssessment.status == "PUBLISHED").limit(1)))
    resubmission_grade_cap = "B" if was_peer_reviewed else None
    v = SubmissionVersion(submission_id=s.id, version_no=s.current_version_no, submitted_by=user.id, submitted_at=submitted_at, member_snapshot=snapshot, is_late=a.due_at < submitted_at, idempotency_key=idempotency_key, grade_cap=resubmission_grade_cap)
    db.add(v); db.flush()
    old_versions = db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.id != v.id)).all()
    for old in old_versions:
        frozen = db.scalar(select(ReviewAssignment.id).where(ReviewAssignment.submission_version_id == old.id).limit(1)) or db.scalar(select(PeerReview.id).where(PeerReview.submission_version_id == old.id).limit(1)) or db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == old.id).limit(1))
        if not frozen:
            db.execute(delete(VersionFile).where(VersionFile.version_id == old.id))
            db.delete(old)
    s.status = "SUBMITTED"
    for f in files: db.add(VersionFile(version_id=v.id, file_id=f.id))
    db.flush()
    stale_keys = []
    inactive = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == False, file_scope)).all()  # noqa: E712
    for file in inactive:
        if not db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == file.id).limit(1)):
            stale_keys.append(file.storage_path)
            db.delete(file)
    audit(db, user, "SUBMISSION_CREATED", "submission", str(s.id)); db.commit()
    for key in stale_keys:
        storage.delete_object(key)
    return {"id": str(s.id), "submitted_at": v.submitted_at, "is_late": v.is_late}


def latest_personal_submission(db: Session, assignment_id: UUID, user_id: UUID):
    return db.execute(
        select(Submission, SubmissionVersion)
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(Submission.assignment_id == assignment_id, Submission.owner_user_id == user_id, Submission.status == "SUBMITTED")
    ).first()


def require_peer_review_submission(db: Session, assignment_id: UUID, user_id: UUID):
    submitted = latest_personal_submission(db, assignment_id, user_id)
    if not submitted:
        raise ApiError(409, "REVIEWER_SUBMISSION_REQUIRED", "请先提交该作业，再参与互评")
    return submitted


def assessment_payload(item: SubmissionAssessment, evaluator_name: str, annotations: list[dict]) -> dict:
    return {
        "id": str(item.id), "kind": item.kind, "grade": item.grade, "comment": item.comment, "comment_html": item.comment,
        "status": item.status, "version": item.version, "published_at": item.published_at,
        "evaluator_id": str(item.evaluator_id), "evaluator_name": evaluator_name,
        "subject_user_id": str(item.subject_user_id), "submission_version_id": str(item.submission_version_id),
        "annotations": annotations,
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def peer_assessment_summary(db: Session, item: SubmissionAssessment, current_user_id: UUID) -> dict:
    evaluator = db.get(User, item.evaluator_id)
    return {
        "id": str(item.id), "grade": item.grade, "status": item.status, "revision": item.version,
        "published_at": item.published_at, "evaluator_id": str(item.evaluator_id),
        "evaluator_name": evaluator.display_name, "is_current_evaluator": item.evaluator_id == current_user_id,
        "comment": "", "annotations": [], "has_draft": False,
    }


def peer_assessment_for_version(db: Session, version_id: UUID) -> SubmissionAssessment | None:
    return db.scalar(
        select(SubmissionAssessment)
        .where(SubmissionAssessment.submission_version_id == version_id, SubmissionAssessment.kind == "PEER")
        .order_by(SubmissionAssessment.created_at, SubmissionAssessment.id)
    )


def lock_submission_version(db: Session, version_id: UUID) -> None:
    query = (
        select(SubmissionVersion.id)
        .where(SubmissionVersion.id == version_id)
        .with_for_update()
        .with_hint(SubmissionVersion, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
    )
    db.scalar(query)


def assessment_json(db: Session, item: SubmissionAssessment) -> dict:
    evaluator = db.get(User, item.evaluator_id)
    return assessment_payload(item, evaluator.display_name, assessment_annotations(db, item.id))


GRADE_POINTS = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
POINT_GRADES = {value: key for key, value in GRADE_POINTS.items()}


def build_submission_grade_result(assessments: list[SubmissionAssessment], serialize_assessment) -> dict:
    teacher_assessment = next((item for item in assessments if item.kind == "TEACHER" and item.status == "PUBLISHED"), None)
    peer_assessments = [item for item in assessments if item.kind == "PEER" and item.status == "PUBLISHED"]
    peer_grade = None
    if peer_assessments:
        average = sum(GRADE_POINTS[item.grade] for item in peer_assessments) / len(peer_assessments)
        peer_grade = POINT_GRADES[int(average + 0.5)]
    final_grade = teacher_assessment.grade if teacher_assessment else peer_grade
    return {
        "teacher_grade": serialize_assessment(teacher_assessment) if teacher_assessment else None,
        "peer_grade": peer_grade, "peer_review_count": len(peer_assessments),
        "peer_feedbacks": [serialize_assessment(item) for item in peer_assessments],
        "final_grade": final_grade, "grade_source": "TEACHER" if teacher_assessment else "PEER" if peer_grade else None,
        "grading_status": "GRADED" if final_grade else "PENDING_ASSESSMENT",
    }


GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


def assert_submission_update_allowed(db: Session, submission: Submission, current: SubmissionVersion | None) -> None:
    if not current:
        return
    result = submission_grade_result(db, current)
    final_grade = result.get("final_grade")
    if final_grade is None:
        raise ApiError(409, "SUBMISSION_UPDATE_LOCKED", "提交后需要等待互评完成或教师评分后，才能重新提交")
    if GRADE_RANK.get(final_grade, 0) > GRADE_RANK["C"]:
        raise ApiError(409, "SUBMISSION_UPDATE_LOCKED", "最终成绩为 A 或 B，不能更新提交")


def submission_grade_result(db: Session, version: SubmissionVersion) -> dict:
    assessments = list(db.scalars(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id)).all())
    return build_submission_grade_result(assessments, lambda item: assessment_json(db, item))


def displayed_submission_grade_result(db: Session, version: SubmissionVersion, current_result: dict | None = None) -> dict:
    result = current_result or submission_grade_result(db, version)
    if result.get("final_grade") or version.version_no <= 1:
        return {**result, "grade_carried_forward": False, "grade_from_version_no": version.version_no if result.get("final_grade") else None}
    previous_versions = db.scalars(
        select(SubmissionVersion)
        .where(SubmissionVersion.submission_id == version.submission_id, SubmissionVersion.version_no < version.version_no)
        .order_by(SubmissionVersion.version_no.desc())
    ).all()
    for previous in previous_versions:
        previous_result = submission_grade_result(db, previous)
        if previous_result.get("final_grade"):
            return {
                **previous_result,
                "grading_status": "PENDING_REASSESSMENT",
                "grade_carried_forward": True,
                "grade_from_version_no": previous.version_no,
            }
    return {**result, "grade_carried_forward": False, "grade_from_version_no": None}


def missing_submission_grade_result(assignment: Assignment) -> dict:
    overdue = assignment.status in {"PUBLISHED", "CLOSED"} and assignment.due_at <= now()
    return {
        "teacher_grade": None, "peer_grade": None, "peer_review_count": 0, "peer_feedbacks": [],
        "final_grade": "E" if overdue else None, "grade_source": "SYSTEM" if overdue else None,
        "grading_status": "NO_SUBMISSION" if overdue else "PENDING_SUBMISSION",
    }


@app.get("/api/v1/peer-review-assignments")
def peer_review_assignments(user: CurrentUser, db: Db, class_id: UUID = Query()):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    require_class(db, user, class_id)
    _, team = require_team(db, class_id, user)
    teammate_ids = select(TeamMember.user_id).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE", TeamMember.user_id != user.id)
    items = []
    assignments = db.scalars(select(Assignment).where(Assignment.class_id == class_id, Assignment.submitter_type == "INDIVIDUAL", Assignment.status.in_(["PUBLISHED", "CLOSED"])).order_by(Assignment.created_at.desc())).all()
    for assignment in assignments:
        if not latest_personal_submission(db, assignment.id, user.id):
            continue
        versions = db.execute(
            select(SubmissionVersion.id, Submission.owner_user_id, User.display_name, User.login_name)
            .join(Submission, Submission.id == SubmissionVersion.submission_id)
            .join(User, User.id == Submission.owner_user_id)
            .where(Submission.assignment_id == assignment.id, Submission.owner_user_id.in_(teammate_ids), Submission.status == "SUBMITTED", SubmissionVersion.version_no == Submission.current_version_no)
            .order_by(User.login_name)
        ).all()
        if not versions: continue
        version_ids = [row.id for row in versions]
        reviewed_version_ids = set(db.scalars(select(SubmissionAssessment.submission_version_id).where(SubmissionAssessment.submission_version_id.in_(version_ids), SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "PEER")).all())
        candidates = [
            {
                "user_id": str(row.owner_user_id), "name": row.display_name, "student_no": row.login_name,
                "reviewed": row.id in reviewed_version_ids,
            }
            for row in versions
        ]
        payload = assignment_json(assignment)
        payload.update({"assignment_id": str(assignment.id), "assignment_title": assignment.title, "available_count": len(versions), "reviewed_count": len(reviewed_version_ids), "pending_count": len(versions) - len(reviewed_version_ids), "candidates": candidates})
        items.append(payload)
    return {"items": items, "total": len(items)}


@app.get("/api/v1/assignments/{aid}/peer-review")
def peer_review_detail(aid: UUID, user: CurrentUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or assignment.status not in {"PUBLISHED", "CLOSED"}: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    require_peer_review_submission(db, aid, user.id)
    _, team = require_team(db, assignment.class_id, user)
    attachments = db.scalars(
        select(FileObject)
        .where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT", FileObject.active == True, or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"))  # noqa: E712
        .order_by(FileObject.created_at)
    ).all()
    criteria_files = db.scalars(
        select(FileObject)
        .where(
            FileObject.assignment_id == aid,
            FileObject.active == True,  # noqa: E712
            or_(FileObject.purpose == "REVIEW_CRITERIA", and_(FileObject.purpose == "ATTACHMENT", FileObject.material_type == "CRITERIA")),
        )
        .order_by(FileObject.created_at)
    ).all()
    review_criteria = db.scalars(
        select(FileObject)
        .where(
            FileObject.assignment_id == aid,
            FileObject.purpose == "ATTACHMENT",
            FileObject.material_type == "CRITERIA",
            FileObject.active == True,  # noqa: E712
        )
        .order_by(FileObject.created_at)
    ).all()
    reviewer_submission, _ = own_submission(db, assignment, user)
    criteria_unlocked = bool(reviewer_submission and reviewer_submission.status == "SUBMITTED")
    rows = db.execute(
        select(Submission, SubmissionVersion, User)
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .join(User, User.id == Submission.owner_user_id)
        .join(TeamMember, and_(TeamMember.user_id == Submission.owner_user_id, TeamMember.team_id == team.id, TeamMember.status == "ACTIVE"))
        .where(Submission.assignment_id == aid, Submission.owner_user_id != user.id, Submission.status == "SUBMITTED")
        .order_by(User.login_name)
    ).all()
    candidates = []
    for submission_item, version, person in rows:
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
        claimed_review = peer_assessment_for_version(db, version.id)
        own_review = claimed_review if claimed_review and claimed_review.evaluator_id == user.id else None
        was_peer_reviewed = bool(claimed_review and claimed_review.status == "PUBLISHED")
        candidates.append({
            "user_id": str(person.id), "name": person.display_name, "student_no": person.login_name,
            "submitted_at": version.submitted_at, "submission_version_id": str(version.id),
            "grade_cap": "B" if version.grade_cap == "B" or was_peer_reviewed else None,
            "files": [file_json(file) for file in files],
            "review": assessment_json(db, own_review) if own_review else (peer_assessment_summary(db, claimed_review, user.id) if claimed_review else None),
            "can_review": claimed_review is None or bool(own_review),
            "can_edit": bool(own_review),
        })
    return {
        "assignment": assignment_json(assignment),
        "attachments": [file_json(file) for file in attachments],
        "review_criteria": [file_json(file) for file in review_criteria] if criteria_unlocked else [],
        "review_criteria_locked": bool(review_criteria and not criteria_unlocked),
        "criteria_files": [file_json(file) for file in criteria_files],
        "team": {"id": str(team.id), "name": team.name},
        "candidates": candidates,
    }


@app.post("/api/v1/assignments/{aid}/peer-reviews", status_code=201)
def save_peer_submission_assessment(aid: UUID, data: PeerSubmissionAssessmentIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or assignment.status not in {"PUBLISHED", "CLOSED"}: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    require_peer_review_submission(db, aid, user.id)
    if data.reviewee_id == user.id: raise ApiError(422, "SELF_REVIEW_FORBIDDEN", "不能评价自己的作业")
    reviewer_team = membership(db, assignment.class_id, user.id)
    reviewee_team = membership(db, assignment.class_id, data.reviewee_id)
    if not reviewer_team or not reviewee_team or reviewer_team[1].id != reviewee_team[1].id: raise ApiError(403, "TEAM_REVIEW_ONLY", "只能评价本组成员的作业")
    submitted = latest_personal_submission(db, aid, data.reviewee_id)
    if not submitted: raise ApiError(409, "REVIEWEE_NOT_SUBMITTED", "该组员尚未提交作业")
    _, version = submitted
    lock_submission_version(db, version.id)
    item = peer_assessment_for_version(db, version.id)
    if item and item.evaluator_id != user.id:
        evaluator = db.get(User, item.evaluator_id)
        raise ApiError(409, "PEER_REVIEW_TAKEN", f"该作品已由{evaluator.display_name}评价，不能重复评价或修改")
    was_peer_reviewed = bool(item and item.status == "PUBLISHED")
    if data.grade == "A" and (version.grade_cap == "B" or was_peer_reviewed):
        raise ApiError(409, "GRADE_CAP_EXCEEDED", "该作业已被互评，后续学生互评最高成绩为 B")
    updating = item is not None
    if item:
        item.grade, item.comment, item.status, item.published_at = data.grade, data.comment.strip(), "PUBLISHED", now()
        item.version += 1
    else:
        item = SubmissionAssessment(assignment_id=aid, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=data.reviewee_id, kind="PEER", grade=data.grade, comment=data.comment.strip(), status="PUBLISHED", published_at=now())
        db.add(item)
    db.flush(); audit(db, user, "PEER_ASSESSMENT_UPDATED" if updating else "PEER_ASSESSMENT_SUBMITTED", "submission_assessment", str(item.id), {"grade": data.grade, "subject_user_id": str(data.reviewee_id)}); db.commit()
    return {**assessment_json(db, item), "updated": updating}


@app.post("/api/v1/assignments/{aid}/submissions/{student_id}/grade", status_code=201)
def save_teacher_submission_assessment(aid: UUID, student_id: UUID, data: SubmissionAssessmentIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    submitted = latest_personal_submission(db, aid, student_id)
    if not submitted: raise ApiError(409, "SUBMISSION_REQUIRED", "该学生尚未提交作业")
    _, version = submitted
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    updating = item is not None
    if item:
        item.grade, item.comment, item.status, item.published_at = data.grade, clean_html(data.comment), "PUBLISHED", now()
        item.version += 1
    else:
        item = SubmissionAssessment(assignment_id=aid, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=student_id, kind="TEACHER", grade=data.grade, comment=clean_html(data.comment), status="PUBLISHED", published_at=now())
        db.add(item)
    db.flush(); audit(db, user, "TEACHER_ASSESSMENT_UPDATED" if updating else "TEACHER_ASSESSMENT_SUBMITTED", "submission_assessment", str(item.id), {"grade": data.grade, "subject_user_id": str(student_id)}); db.commit()
    return {**assessment_json(db, item), "updated": updating, "result": submission_grade_result(db, version)}


@app.delete("/api/v1/assignments/{aid}/submissions/{student_id}/grade")
def delete_teacher_submission_assessment(aid: UUID, student_id: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    submitted = latest_personal_submission(db, aid, student_id)
    if not submitted: raise ApiError(409, "SUBMISSION_REQUIRED", "该学生尚未提交作业")
    _, version = submitted
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    if item:
        item_id = str(item.id); db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == item.id)); db.delete(item); db.flush(); audit(db, user, "TEACHER_ASSESSMENT_CLEARED", "submission_assessment", item_id)
    result = submission_grade_result(db, version); db.commit()
    return result


def feedback_context(db: Session, version_id: UUID, user: User):
    row = db.execute(
        select(SubmissionVersion, Submission, Assignment)
        .join(Submission, Submission.id == SubmissionVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(SubmissionVersion.id == version_id)
    ).first()
    if not row: raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    version, submission_item, assignment = row
    if user.role == "TEACHER":
        if not user_class(db, user, assignment.class_id): raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    elif submission_item.owner_user_id != user.id:
        team_row = membership(db, assignment.class_id, user.id) if submission_item.owner_team_id else None
        if not team_row or team_row[1].id != submission_item.owner_team_id:
            raise ApiError(403, "FEEDBACK_FORBIDDEN", "无权查看该提交反馈")
    return version, submission_item, assignment


def annotation_json(item: SubmissionAnnotation) -> dict:
    mark_type = item.mark_type or ("COMMENT" if item.comment else "HIGHLIGHT")
    return {"id": str(item.id), "file_id": str(item.file_id), "kind": item.kind, "mark_type": mark_type, "color": item.color or "YELLOW", "anchor": item.anchor, "comment": item.comment, "created_at": item.created_at, "updated_at": item.updated_at}


def assessment_annotations(db: Session, assessment_id: UUID) -> list[dict]:
    items = db.scalars(select(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == assessment_id).order_by(SubmissionAnnotation.position, SubmissionAnnotation.created_at)).all()
    return [annotation_json(item) for item in items]


def feedback_json(db: Session, item: SubmissionAssessment | None, include_draft: bool = False) -> dict:
    if not item:
        return {"status": None, "revision": 0, "grade": None, "comment": "", "annotations": [], "published_at": None, "has_draft": False}
    published = {"grade": item.grade, "comment": item.comment, "annotations": assessment_annotations(db, item.id)}
    draft = item.draft_payload if include_draft and item.draft_payload else None
    payload = draft or published
    return {
        "id": str(item.id), "status": "DRAFT" if draft or item.status == "DRAFT" else "PUBLISHED",
        "published_status": item.status, "revision": item.version, "published_at": item.published_at,
        "has_draft": bool(draft), "grade": payload["grade"], "comment": payload.get("comment", ""),
        "annotations": payload.get("annotations", []),
    }


def validate_feedback_annotations(db: Session, version_id: UUID, annotations: list[SubmissionAnnotationIn]) -> list[dict]:
    payload = []
    for annotation in annotations:
        linked = db.scalar(select(VersionFile.file_id).where(VersionFile.version_id == version_id, VersionFile.file_id == annotation.file_id))
        file = db.get(FileObject, annotation.file_id) if linked else None
        if not file: raise ApiError(422, "ANNOTATION_FILE_INVALID", "批注文件不属于该提交版本")
        suffix = Path(file.original_name).suffix.lower()
        anchor = annotation.anchor
        cleaned_comment = clean_html(annotation.comment)
        mark_type = annotation.mark_type or ("COMMENT" if annotation.comment.strip() else "HIGHLIGHT")
        if annotation.kind == "PDF_TEXT_OR_REGION":
            rects = anchor.get("rects") if isinstance(anchor, dict) else None
            if suffix != ".pdf" or not isinstance(anchor.get("page"), int) or anchor["page"] < 1 or not isinstance(rects, list) or not rects or len(rects) > 100:
                raise ApiError(422, "ANNOTATION_ANCHOR_INVALID", "PDF 批注锚点无效")
            for rect in rects:
                if not isinstance(rect, dict) or any(not isinstance(rect.get(key), (int, float)) for key in ("x", "y", "width", "height")) or rect["width"] <= 0 or rect["height"] <= 0 or any(rect[key] < 0 or rect[key] > 1 for key in ("x", "y", "width", "height")) or rect["x"] + rect["width"] > 1.001 or rect["y"] + rect["height"] > 1.001:
                    raise ApiError(422, "ANNOTATION_ANCHOR_INVALID", "PDF 批注坐标无效")
            if not str(anchor.get("quote", "")).strip() and mark_type not in {"HIGHLIGHT", "COMMENT"}:
                raise ApiError(422, "ANNOTATION_MARK_TYPE_INVALID", "PDF 区域批注仅支持高亮或评论")
        else:
            start, end = anchor.get("start") if isinstance(anchor, dict) else None, anchor.get("end") if isinstance(anchor, dict) else None
            valid_point = lambda point: isinstance(point, dict) and isinstance(point.get("block_id"), str) and bool(re.fullmatch(r"b\d+", point["block_id"])) and isinstance(point.get("offset"), int) and point["offset"] >= 0
            if suffix not in {".md", ".html", ".htm"} or not valid_point(start) or not valid_point(end) or len(str(anchor.get("exact", ""))) > 4000:
                raise ApiError(422, "ANNOTATION_ANCHOR_INVALID", "富文本批注锚点无效")
        payload.append({"id": str(annotation.id) if annotation.id else None, "file_id": str(annotation.file_id), "kind": annotation.kind, "mark_type": mark_type, "color": annotation.color, "anchor": anchor, "comment": cleaned_comment})
    return payload


def replace_feedback_annotations(db: Session, item: SubmissionAssessment, annotations: list[dict], user: User) -> None:
    db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == item.id))
    for position, annotation in enumerate(annotations):
        db.add(SubmissionAnnotation(assessment_id=item.id, submission_version_id=item.submission_version_id, file_id=UUID(annotation["file_id"]), author_id=user.id, kind=annotation["kind"], mark_type=annotation.get("mark_type") or ("COMMENT" if annotation.get("comment") else "HIGHLIGHT"), color=annotation.get("color") or "YELLOW", anchor=annotation["anchor"], comment=annotation["comment"], position=position))


def peer_feedback_context(db: Session, version_id: UUID, user: User):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    row = db.execute(
        select(SubmissionVersion, Submission, Assignment)
        .join(Submission, Submission.id == SubmissionVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(SubmissionVersion.id == version_id)
    ).first()
    if not row: raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    version, submission_item, assignment = row
    if assignment.submitter_type != "INDIVIDUAL" or assignment.status not in {"PUBLISHED", "CLOSED"}:
        raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    require_class(db, user, assignment.class_id)
    require_peer_review_submission(db, assignment.id, user.id)
    if submission_item.owner_user_id == user.id: raise ApiError(422, "SELF_REVIEW_FORBIDDEN", "不能评价自己的作业")
    reviewer_team = membership(db, assignment.class_id, user.id)
    reviewee_team = membership(db, assignment.class_id, submission_item.owner_user_id)
    if not reviewer_team or not reviewee_team or reviewer_team[1].id != reviewee_team[1].id:
        raise ApiError(403, "TEAM_REVIEW_ONLY", "只能评价本组成员的作业")
    if submission_item.status != "SUBMITTED" or submission_item.current_version_no != version.version_no:
        raise ApiError(409, "SUBMISSION_VERSION_READ_ONLY", "只能评价最新正式提交版本")
    return version, submission_item, assignment


@app.get("/api/v1/submission-versions/{version_id}/peer-feedback")
def get_peer_submission_feedback(version_id: UUID, user: CurrentUser, db: Db):
    version, _, _ = peer_feedback_context(db, version_id, user)
    item = peer_assessment_for_version(db, version.id)
    if item and item.evaluator_id != user.id:
        evaluator = db.get(User, item.evaluator_id)
        raise ApiError(409, "PEER_REVIEW_TAKEN", f"该作品已由{evaluator.display_name}评价，不能重复评价或修改")
    return feedback_json(db, item)


@app.post("/api/v1/submission-versions/{version_id}/peer-feedback/publish")
def publish_peer_submission_feedback(version_id: UUID, data: SubmissionFeedbackIn, user: CsrfUser, db: Db):
    version, submission_item, assignment = peer_feedback_context(db, version_id, user)
    require_writable_class(db, user, assignment.class_id)
    lock_submission_version(db, version.id)
    item = peer_assessment_for_version(db, version.id)
    if item and item.evaluator_id != user.id:
        evaluator = db.get(User, item.evaluator_id)
        raise ApiError(409, "PEER_REVIEW_TAKEN", f"该作品已由{evaluator.display_name}评价，不能重复评价或修改")
    current_revision = item.version if item else 0
    if data.revision != current_revision: raise ApiError(409, "FEEDBACK_VERSION_CONFLICT", "反馈已在其他页面更新，请刷新后重试")
    was_peer_reviewed = bool(db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.kind == "PEER", SubmissionAssessment.status == "PUBLISHED").limit(1)))
    if data.grade == "A" and (version.grade_cap == "B" or was_peer_reviewed):
        raise ApiError(409, "GRADE_CAP_EXCEEDED", "该作业已被互评，后续学生互评最高成绩为 B")
    annotations = validate_feedback_annotations(db, version.id, data.annotations)
    comment = clean_html(data.comment)
    updating = item is not None
    if item:
        item.grade, item.comment, item.status, item.published_at, item.draft_payload = data.grade, comment, "PUBLISHED", now(), None
        item.version += 1
    else:
        item = SubmissionAssessment(assignment_id=assignment.id, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=submission_item.owner_user_id, kind="PEER", grade=data.grade, comment=comment, status="PUBLISHED", published_at=now())
        db.add(item); db.flush()
    replace_feedback_annotations(db, item, annotations, user)
    audit(db, user, "PEER_ASSESSMENT_UPDATED" if updating else "PEER_ASSESSMENT_SUBMITTED", "submission_assessment", str(item.id), {"grade": data.grade, "subject_user_id": str(submission_item.owner_user_id), "annotation_count": len(annotations)})
    db.commit(); db.refresh(item)
    return {**feedback_json(db, item), "updated": updating, "result": submission_grade_result(db, version)}


def save_submission_feedback(version_id: UUID, data: SubmissionFeedbackIn, user: User, db: Session, publish: bool) -> dict:
    teacher(user)
    version, submission_item, assignment = feedback_context(db, version_id, user)
    require_writable_class(db, user, assignment.class_id)
    subject_user_id = submission_item.owner_user_id or version.submitted_by
    if submission_item.current_version_no != version.version_no: raise ApiError(409, "SUBMISSION_VERSION_READ_ONLY", "历史提交版本只能查看")
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER").with_for_update())
    current_revision = item.version if item else 0
    if data.revision != current_revision: raise ApiError(409, "FEEDBACK_VERSION_CONFLICT", "反馈已在其他页面更新，请刷新后重试")
    annotations = validate_feedback_annotations(db, version.id, data.annotations)
    payload = {"grade": data.grade, "comment": clean_html(data.comment), "annotations": annotations}
    if not item:
        item = SubmissionAssessment(assignment_id=assignment.id, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=subject_user_id, kind="TEACHER", grade=data.grade, comment=payload["comment"], status="PUBLISHED" if publish else "DRAFT", published_at=now() if publish else None)
        db.add(item); db.flush()
        replace_feedback_annotations(db, item, annotations, user)
    elif publish:
        item.grade, item.comment, item.status, item.published_at, item.draft_payload = data.grade, payload["comment"], "PUBLISHED", now(), None
        item.version += 1
        replace_feedback_annotations(db, item, annotations, user)
    elif item.status == "PUBLISHED":
        item.draft_payload = payload
        item.version += 1
    else:
        item.grade, item.comment = data.grade, payload["comment"]
        item.version += 1
        replace_feedback_annotations(db, item, annotations, user)
    action = "TEACHER_FEEDBACK_PUBLISHED" if publish else "TEACHER_FEEDBACK_DRAFT_SAVED"
    audit(db, user, action, "submission_assessment", str(item.id), {"submission_version_id": str(version.id), "annotation_count": len(annotations)})
    db.commit(); db.refresh(item)
    return {**feedback_json(db, item, True), "result": submission_grade_result(db, version)}


@app.get("/api/v1/submission-versions/{version_id}/feedback")
def get_submission_feedback(version_id: UUID, user: CurrentUser, db: Db):
    version, _, _ = feedback_context(db, version_id, user)
    query = select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.kind == "TEACHER")
    if user.role == "TEACHER": query = query.where(SubmissionAssessment.evaluator_id == user.id)
    else: query = query.where(SubmissionAssessment.status == "PUBLISHED")
    item = db.scalar(query.order_by(SubmissionAssessment.updated_at.desc()))
    return feedback_json(db, item, user.role == "TEACHER")


@app.put("/api/v1/submission-versions/{version_id}/feedback/draft")
def save_submission_feedback_draft(version_id: UUID, data: SubmissionFeedbackIn, user: CsrfUser, db: Db):
    return save_submission_feedback(version_id, data, user, db, False)


@app.post("/api/v1/submission-versions/{version_id}/feedback/publish")
def publish_submission_feedback(version_id: UUID, data: SubmissionFeedbackIn, user: CsrfUser, db: Db):
    return save_submission_feedback(version_id, data, user, db, True)


@app.delete("/api/v1/submission-versions/{version_id}/feedback")
def delete_submission_feedback(version_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    version, _, assignment = feedback_context(db, version_id, user)
    require_writable_class(db, user, assignment.class_id)
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    if item:
        item_id = str(item.id); db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == item.id)); db.delete(item); db.flush(); audit(db, user, "TEACHER_ASSESSMENT_CLEARED", "submission_assessment", item_id)
    result = submission_grade_result(db, version); db.commit()
    return result


def require_file_access(db: Session, user: User, fid: UUID) -> FileObject:
    f = db.get(FileObject, fid); a = db.get(Assignment, f.assignment_id) if f else None
    if not f or not a: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_class(db, user, a.class_id); allowed = user.role == "TEACHER" or f.owner_id == user.id
    if user.role == "STUDENT":
        own_membership = membership(db, a.class_id, user.id)
        mine = own_membership[1] if own_membership else None
        if f.purpose == "ATTACHMENT": allowed = True
        if f.purpose == "REVIEW_CRITERIA" or (f.purpose == "ATTACHMENT" and f.material_type == "CRITERIA"):
            submission, _ = own_submission(db, a, user)
            allowed = bool(submission and submission.status == "SUBMITTED")
        elif f.team_id: allowed = bool(mine and f.team_id == mine.id)
        elif not allowed:
            frozen = db.scalar(select(ReviewAssignment.id).join(ReviewCampaign, ReviewCampaign.id == ReviewAssignment.campaign_id).join(VersionFile, VersionFile.version_id == ReviewAssignment.submission_version_id).where(ReviewCampaign.assignment_id == a.id, ReviewAssignment.reviewer_id == user.id, VersionFile.file_id == f.id, ReviewAssignment.status.in_(["PENDING", "COMPLETED"])).limit(1))
            if frozen:
                allowed = True
            else:
                owner = membership(db, a.class_id, f.owner_id)
                linked = db.execute(select(SubmissionVersion, Submission).join(Submission, Submission.id == SubmissionVersion.submission_id).join(VersionFile, VersionFile.version_id == SubmissionVersion.id).where(VersionFile.file_id == f.id, Submission.status == "SUBMITTED", Submission.current_version_no == SubmissionVersion.version_no)).first()
                reviewer_submitted = latest_personal_submission(db, a.id, user.id)
                allowed = bool(owner and mine and owner[1].id == mine.id and linked and reviewer_submitted)
    if not allowed: raise ApiError(403, "FILE_FORBIDDEN", "无权访问该文件")
    return f


@app.get("/api/v1/files/{fid}")
def download(fid: UUID, user: CurrentUser, db: Db):
    f = require_file_access(db, user, fid)
    try:
        stream = storage.get_object_stream(f.storage_path)
    except NoSuchKey:
        raise ApiError(404, "FILE_MISSING", "文件存储不可用")
    return StreamingResponse(stream, media_type=f.detected_mime, headers={"Content-Disposition": content_disposition(f.original_name)})


@app.post("/api/v1/review-campaigns", status_code=201)
def create_campaign(data: AllocatedCampaignIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == data.assignment_id).with_for_update())
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    writable_teacher_classes(db, user, [assignment.class_id])
    if assignment.submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "互评只能关联个人作业")
    if assignment.due_at >= now(): raise ApiError(409, "ASSIGNMENT_NOT_CLOSED", "作业截止后才能创建互评")
    if data.due_at <= now(): raise ApiError(422, "CAMPAIGN_TIME_INVALID", "互评截止时间必须晚于当前时间")
    if db.scalar(select(ReviewCampaign.id).where(ReviewCampaign.assignment_id == assignment.id)): raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
    criteria_ids = set(data.criteria_file_ids)
    criteria_files = db.scalars(select(FileObject).where(FileObject.id.in_(criteria_ids), FileObject.assignment_id == assignment.id, FileObject.purpose == "REVIEW_CRITERIA")).all() if criteria_ids else []
    if len(criteria_files) != len(criteria_ids): raise ApiError(422, "CRITERIA_FILE_INVALID", "互评标准附件不存在或不属于关联作业")
    if not data.criteria_text.strip() and not criteria_files: raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "互评标准文字和附件至少提供一种")

    frozen_rows = db.execute(
        select(User, SubmissionVersion)
        .join(ClassMember, and_(ClassMember.user_id == User.id, ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT"))
        .join(Submission, and_(Submission.owner_user_id == User.id, Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED"))
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(User.status == "ACTIVE")
        .order_by(User.login_name)
        .with_for_update()
    ).all()
    if len(frozen_rows) < 2: raise ApiError(409, "REVIEW_CANDIDATES_INSUFFICIENT", "全班已正式提交学生少于 2 人，不能创建互评")

    snapshot_at = now()
    campaign = ReviewCampaign(assignment_id=assignment.id, class_id=assignment.class_id, mode=data.mode, criteria_text=data.criteria_text.strip(), assignment_snapshot_at=snapshot_at, rubric=[{"key": "score", "label": "总分", "weight": 100}], comment_min_length=1, due_at=data.due_at, publish_at=snapshot_at, require_all=False, allow_update=True)
    db.add(campaign); db.flush()
    warnings = []
    team_by_user = {
        user_id: team_id
        for user_id, team_id in db.execute(
            select(TeamMember.user_id, TeamMember.team_id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.class_id == assignment.class_id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")
        ).all()
    }
    if data.mode == "CLASS":
        groups = [("CLASS", "教学班", frozen_rows)]
    else:
        grouped = {(team.id, team.name): [] for team in db.scalars(select(Team).where(Team.class_id == assignment.class_id, Team.status == "ACTIVE")).all()}
        for person, version in frozen_rows:
            team_row = db.execute(select(TeamMember.team_id, Team.name).join(Team, Team.id == TeamMember.team_id).where(TeamMember.class_id == assignment.class_id, TeamMember.user_id == person.id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")).first()
            key, label = (team_row.team_id, team_row.name) if team_row else (None, "未分组")
            grouped.setdefault((key, label), []).append((person, version))
        groups = [(str(key), label, rows) for (key, label), rows in grouped.items()]
    allocations = []
    for _, label, rows in groups:
        if len(rows) < 2:
            reason = f"{label} 已正式提交人数少于 2 人"
            warnings.append({"group": label, "reason": reason, "count": len(rows)})
            for person, _ in rows:
                allocations.append(ReviewAssignment(campaign_id=campaign.id, reviewer_id=person.id, participant_team_id=team_by_user.get(person.id), status="SKIPPED", skip_reason=reason))
            continue
        for index, (reviewer, _) in enumerate(rows):
            reviewee, version = rows[(index + 1) % len(rows)]
            allocations.append(ReviewAssignment(campaign_id=campaign.id, reviewer_id=reviewer.id, participant_team_id=team_by_user.get(reviewer.id), reviewee_id=reviewee.id, submission_version_id=version.id))
            notify(db, reviewer.id, "REVIEW_ASSIGNED", f"新的互评任务：{assignment.title}")
    db.add_all(allocations)
    audit(db, user, "REVIEW_CAMPAIGN_CREATED", "review_campaign", str(campaign.id), {"mode": data.mode, "allocated": sum(x.status == "PENDING" for x in allocations), "skipped": sum(x.status == "SKIPPED" for x in allocations)})
    try: db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
    return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "status": campaign.status, "mode": campaign.mode, "assignment_snapshot_at": campaign.assignment_snapshot_at, "allocated": sum(x.status == "PENDING" for x in allocations), "skipped": sum(x.status == "SKIPPED" for x in allocations), "warnings": warnings}


@app.get("/api/v1/review-campaigns")
def campaigns(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    query = select(ReviewCampaign, Assignment).join(Assignment).where(ReviewCampaign.class_id == class_id, Assignment.submitter_type == "INDIVIDUAL")
    if user.role == "STUDENT": query = query.where(or_(ReviewCampaign.publish_at.is_(None), ReviewCampaign.publish_at <= now()))
    rows = db.execute(query.order_by(ReviewCampaign.due_at.desc())).all()
    items = []
    for c, a in rows:
        payload = {"id": str(c.id), "assignment_id": str(a.id), "assignment_title": a.title, "mode": c.mode, "criteria_text": c.criteria_text, "assignment_snapshot_at": c.assignment_snapshot_at, "rubric": c.rubric, "comment_min_length": c.comment_min_length, "due_at": c.due_at, "publish_at": c.publish_at, "require_all": c.require_all, "allow_update": c.allow_update, "status": c.status, "grades_generated_at": c.grades_generated_at, "version": c.version, "completed": db.scalar(select(func.count()).select_from(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.status == "VALID")) or 0}
        if user.role == "STUDENT":
            allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == c.id, ReviewAssignment.reviewer_id == user.id))
            payload["pending_count"] = 1 if allocation and allocation.status == "PENDING" else 0
            payload["allocation_status"] = allocation.status if allocation else None
            payload["skip_reason"] = allocation.skip_reason if allocation else None
        items.append(payload)
    return {"items": items, "total": len(items)}


@app.get("/api/v1/review-campaigns/{cid}/assignment")
def allocated_assignment(cid: UUID, user: CurrentUser, db: Db):
    campaign = db.get(ReviewCampaign, cid)
    if not campaign: raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_class(db, user, campaign.class_id)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生查看自己的互评任务")
    allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == cid, ReviewAssignment.reviewer_id == user.id))
    if not allocation: raise ApiError(404, "REVIEW_ASSIGNMENT_NOT_FOUND", "当前活动没有分配给你的任务")
    assignment = db.get(Assignment, campaign.assignment_id)
    if not assignment or assignment.submitter_type != "INDIVIDUAL":
        raise ApiError(404, "CAMPAIGN_NOT_FOUND", "小组作业不参与互评")
    criteria_files = db.scalars(select(FileObject).where(FileObject.assignment_id == campaign.assignment_id, FileObject.purpose == "REVIEW_CRITERIA").order_by(FileObject.created_at)).all()
    payload = {
        "id": str(allocation.id), "status": allocation.status, "skip_reason": allocation.skip_reason,
        "campaign": {"id": str(campaign.id), "assignment_title": assignment.title, "mode": campaign.mode, "criteria_text": campaign.criteria_text or "", "due_at": campaign.due_at, "assignment_snapshot_at": campaign.assignment_snapshot_at, "criteria_files": [file_json(file, db.get(User, file.owner_id).display_name) for file in criteria_files]},
        "reviewee": None, "submission": None, "review": None,
    }
    if allocation.reviewee_id and allocation.submission_version_id:
        reviewee = db.get(User, allocation.reviewee_id); version = db.get(SubmissionVersion, allocation.submission_version_id)
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
        review = db.scalar(select(PeerReview).where(PeerReview.allocation_id == allocation.id, PeerReview.status == "VALID"))
        payload["reviewee"] = {"id": str(reviewee.id), "name": reviewee.display_name, "student_no": reviewee.login_name}
        payload["submission"] = {"submitted_at": version.submitted_at, "files": [file_json(file, reviewee.display_name, True) for file in files]}
        if review: payload["review"] = {"id": str(review.id), "score": review.total_score, "comment": review.comment, "status": review.status}
    return payload


@app.post("/api/v1/review-campaigns/{cid}/reviews", status_code=201)
def review(cid: UUID, data: ReviewIn, user: CsrfUser, db: Db):
    c = db.get(ReviewCampaign, cid)
    if not c or c.status != "ACTIVE" or (c.publish_at and c.publish_at > now()) or c.due_at < now(): raise ApiError(409, "CAMPAIGN_CLOSED", "互评活动未开放或已截止")
    assignment = db.get(Assignment, c.assignment_id)
    if not assignment or assignment.submitter_type != "INDIVIDUAL":
        raise ApiError(409, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "小组作业不参与互评")
    require_writable_class(db, user, c.class_id)
    allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == c.id, ReviewAssignment.reviewer_id == user.id).with_for_update())
    if not allocation: raise ApiError(403, "REVIEW_NOT_ASSIGNED", "当前活动没有分配给你的互评任务")
    if allocation.status == "SKIPPED": raise ApiError(409, "REVIEW_ASSIGNMENT_SKIPPED", allocation.skip_reason or "该互评任务已跳过")
    if allocation.status not in {"PENDING", "COMPLETED"}: raise ApiError(409, "REVIEW_DUPLICATE", "该互评任务已提交")
    if allocation.status == "COMPLETED" and not c.allow_update: raise ApiError(409, "REVIEW_UPDATE_DISABLED", "当前互评活动不允许修改已提交评价")
    if data.score is None: raise ApiError(422, "SCORE_REQUIRED", "请填写 0 至 100 的总分")
    comment = data.comment.strip()
    if not comment: raise ApiError(422, "COMMENT_REQUIRED", "评语不能为空")
    existing = db.scalar(select(PeerReview).where(PeerReview.allocation_id == allocation.id))
    updating = allocation.status == "COMPLETED"
    if updating and not existing: raise ApiError(409, "REVIEW_UPDATE_INVALID", "已提交评价记录不存在，请联系教师处理")
    scores = {"score": data.score}
    if existing:
        existing.reviewer_id, existing.reviewee_id, existing.submission_version_id = allocation.reviewer_id, allocation.reviewee_id, allocation.submission_version_id
        existing.scores, existing.total_score, existing.comment, existing.status, existing.invalid_reason = scores, data.score, comment, "VALID", None
        item = existing
    else:
        item = PeerReview(allocation_id=allocation.id, campaign_id=c.id, reviewer_id=allocation.reviewer_id, reviewee_id=allocation.reviewee_id, submission_version_id=allocation.submission_version_id, scores=scores, total_score=data.score, comment=comment)
        db.add(item)
    allocation.status = "COMPLETED"
    if not updating: notify(db, allocation.reviewee_id, "REVIEW_RECEIVED", f"收到来自 {user.display_name} 的作品评价")
    db.flush(); audit(db, user, "PEER_REVIEW_UPDATED" if updating else "PEER_REVIEW_SUBMITTED", "peer_review", str(item.id), {"allocation_id": str(allocation.id)}); db.commit()
    return {"id": str(item.id), "allocation_id": str(allocation.id), "total_score": data.score, "status": item.status, "updated": updating}


@app.get("/api/v1/peer-reviews/received")
def received(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id); reviewer = aliased(User)
    result_visible = or_(ReviewCampaign.due_at <= now(), ReviewCampaign.status == "CLOSED")
    rows = db.execute(select(PeerReview, Assignment, reviewer).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment, Assignment.id == ReviewCampaign.assignment_id).join(reviewer, reviewer.id == PeerReview.reviewer_id).where(PeerReview.reviewee_id == user.id, PeerReview.status == "VALID", ReviewCampaign.class_id == class_id, result_visible)).all()
    return {"items": [{"id": str(r.id), "campaign_id": str(r.campaign_id), "assignment_title": a.title, "reviewer_name": p.display_name, "scores": r.scores, "total_score": r.total_score, "comment": r.comment, "created_at": r.created_at} for r, a, p in rows]}

@app.get("/api/v1/peer-reviews/sent")
def sent_reviews(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    reviewee = aliased(User)
    rows = db.execute(select(PeerReview, Assignment, reviewee).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment, Assignment.id == ReviewCampaign.assignment_id).join(reviewee, reviewee.id == PeerReview.reviewee_id).where(PeerReview.reviewer_id == user.id, ReviewCampaign.class_id == class_id).order_by(PeerReview.updated_at.desc())).all()
    return {"items": [{"id": str(r.id), "campaign_id": str(r.campaign_id), "assignment_title": a.title, "reviewee_name": p.display_name, "scores": r.scores, "total_score": r.total_score, "comment": r.comment, "status": r.status, "created_at": r.created_at, "updated_at": r.updated_at} for r, a, p in rows]}


@app.post("/api/v1/peer-reviews/{rid}/invalidate", status_code=204)
def invalidate(rid: UUID, data: ReasonIn, user: CsrfUser, db: Db):
    teacher(user); x = db.get(PeerReview, rid)
    if not x: raise ApiError(404, "REVIEW_NOT_FOUND", "评价不存在")
    campaign = db.get(ReviewCampaign, x.campaign_id)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "REVIEW_NOT_FOUND", "评价不存在")
    require_writable_class(db, user, campaign.class_id)
    grade = db.scalar(select(Grade).where(Grade.peer_review_id == x.id))
    if grade and grade.status == "PUBLISHED": raise ApiError(409, "PUBLISHED_GRADE_LOCKED", "该评价已形成发布成绩，不能再作废")
    x.status, x.invalid_reason = "INVALID", data.reason
    if x.allocation_id:
        allocation = db.get(ReviewAssignment, x.allocation_id)
        if allocation: allocation.status = "PENDING"
    if grade:
        grade.peer_review_id, grade.peer_score, grade.draft_score, grade.status = None, None, None, "PENDING"
        grade.version += 1
    audit(db, user, "PEER_REVIEW_INVALIDATED", "peer_review", str(x.id), {"reason": data.reason}); db.commit(); return Response(status_code=204)


@app.get("/api/v1/review-campaigns/{cid}/reviews")
def campaign_reviews(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); campaign = db.get(ReviewCampaign, cid)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    reviewer = aliased(User); reviewee = aliased(User)
    rows = db.execute(select(PeerReview, reviewer, reviewee).join(reviewer, reviewer.id == PeerReview.reviewer_id).join(reviewee, reviewee.id == PeerReview.reviewee_id).where(PeerReview.campaign_id == cid).order_by(PeerReview.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "reviewer_name": from_user.display_name, "reviewee_name": to_user.display_name, "total_score": item.total_score, "comment": item.comment, "status": item.status, "invalid_reason": item.invalid_reason, "created_at": item.created_at} for item, from_user, to_user in rows], "total": len(rows)}


@app.get("/api/v1/grades")
def grades(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    if user.role == "STUDENT":
        _, team = require_team(db, class_id, user)
        assignments = db.scalars(select(Assignment).where(Assignment.class_id == class_id, Assignment.status.in_(["PUBLISHED", "CLOSED"])).order_by(Assignment.due_at.desc())).all()
        legacy_rows = db.execute(
            select(Grade, Assignment, GradeCoefficient).select_from(Grade).join(Assignment, Assignment.id == Grade.assignment_id).outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
            .where(Assignment.class_id == class_id, Grade.subject_user_id == user.id, Grade.status == "PUBLISHED")
        ).all()
        legacy_assignment_ids = {grade.assignment_id for grade, _, _ in legacy_rows}
        items = []
        for assignment in assignments:
            if assignment.submitter_type == "INDIVIDUAL":
                submitted = latest_personal_submission(db, assignment.id, user.id)
            else:
                submitted = db.execute(
                    select(Submission, SubmissionVersion)
                    .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
                    .where(Submission.assignment_id == assignment.id, Submission.owner_team_id == team.id, Submission.status == "SUBMITTED")
                ).first()
            if submitted:
                _, version = submitted
                has_current_assessment = bool(db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == version.id).limit(1)))
                if assignment.id in legacy_assignment_ids and not has_current_assessment: continue
                result = displayed_submission_grade_result(db, version)
                files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
                items.append({"id": str(version.id), "submission_version_id": str(version.id), "submission_version_no": version.version_no, "assignment_id": str(assignment.id), "assignment_title": assignment.title, "submitter_type": assignment.submitter_type, "status": result["grading_status"], "files": [file_json(file) for file in files], **result})
            else:
                result = missing_submission_grade_result(assignment)
                if result["final_grade"]:
                    items.append({"id": str(assignment.id), "submission_version_id": None, "submission_version_no": None, "assignment_id": str(assignment.id), "assignment_title": assignment.title, "submitter_type": assignment.submitter_type, "status": result["grading_status"], "files": [], **result})
        new_assignment_ids = {item["assignment_id"] for item in items}
        for grade, assignment, coefficient in legacy_rows:
            if str(assignment.id) not in new_assignment_ids:
                items.append({"id": str(grade.id), "assignment_id": str(assignment.id), "assignment_title": assignment.title, "peer_score": grade.peer_score, "coefficient": coefficient.published_value if coefficient else None, "score": grade.score, "status": grade.status})
        return {"items": items, "total": len(items)}
    query = select(Grade, Assignment, GradeCoefficient).select_from(Grade).join(Assignment, Assignment.id == Grade.assignment_id).outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id).where(Assignment.class_id == class_id)
    rows = db.execute(query.order_by(Grade.updated_at.desc())).all(); items = []
    for g, a, coefficient in rows:
        person = db.get(User, g.subject_user_id)
        team_item = db.get(Team, coefficient.team_id) if coefficient else None
        items.append({"id": str(g.id), "assignment_id": str(a.id), "assignment_title": a.title, "subject_id": str(person.id), "subject_name": person.display_name, "student_no": person.login_name, "team_name": team_item.name if team_item else "未分组", "peer_score": g.peer_score, "coefficient": coefficient.published_value if coefficient else None, "score": g.score, "status": g.status, "version": g.version})
    return {"items": items, "total": len(items)}


@app.get("/api/v1/grades/assignments")
def grade_assignments(user: CurrentUser, db: Db, class_id: UUID = Query()):
    teacher(user); require_class(db, user, class_id)
    rows = db.scalars(select(Assignment).where(Assignment.class_id == class_id, Assignment.submitter_type == "INDIVIDUAL").order_by(Assignment.due_at.desc())).all()
    total_students = db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.class_id == class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")) or 0
    items = []
    for assignment in rows:
        campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment.id))
        submissions = db.scalars(select(Submission).where(Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED")).all()
        graded = 0
        for submission_item in submissions:
            version = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == submission_item.id, SubmissionVersion.version_no == submission_item.current_version_no))
            if version and submission_grade_result(db, version)["final_grade"]: graded += 1
        if missing_submission_grade_result(assignment)["final_grade"]:
            graded += max(0, total_students - len(submissions))
        items.append({
            "id": str(assignment.id), "title": assignment.title, "due_at": assignment.due_at, "status": assignment.status,
            "campaign_id": str(campaign.id) if campaign else None, "campaign_status": campaign.status if campaign else None,
            "grades_generated_at": campaign.grades_generated_at if campaign else None,
            "total": total_students, "submitted": len(submissions), "graded": graded, "pending": max(0, total_students - graded),
        })
    return {"items": items, "total": len(items)}


def require_grade_assignment(db: Session, user: User, assignment_id: UUID) -> tuple[Assignment, ReviewCampaign]:
    assignment = db.get(Assignment, assignment_id)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment_id, ReviewCampaign.assignment_snapshot_at.is_not(None)))
    if not campaign: raise ApiError(404, "GRADEBOOK_NOT_FOUND", "该作业没有一对一互评成绩")
    return assignment, campaign


@app.get("/api/v1/grades/assignments/{assignment_id}")
def grade_assignment_detail(assignment_id: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment, campaign = require_grade_assignment(db, user, assignment_id)
    rows = db.execute(
        select(Grade, User, GradeCoefficient, Team)
        .join(User, User.id == Grade.subject_user_id)
        .outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
        .outerjoin(Team, Team.id == GradeCoefficient.team_id)
        .where(Grade.assignment_id == assignment_id)
        .order_by(Team.name, User.login_name)
    ).all()
    items = []
    for grade, person, coefficient, team_item in rows:
        changed = bool(grade.status == "PUBLISHED" and grade.draft_score is not None and grade.draft_score != grade.score)
        if grade.peer_score is None: display_status = "PENDING_REVIEW"
        elif not coefficient or coefficient.draft_value is None: display_status = "PENDING_COEFFICIENT"
        elif changed: display_status = "CHANGED"
        else: display_status = grade.status
        items.append({
            "id": str(grade.id), "user_id": str(person.id), "student_no": person.login_name, "student_name": person.display_name,
            "team_id": str(team_item.id) if team_item else None, "team_name": team_item.name if team_item else "未分组",
            "peer_score": grade.peer_score, "draft_coefficient": coefficient.draft_value if coefficient else None,
            "published_coefficient": coefficient.published_value if coefficient else None, "draft_score": grade.draft_score,
            "score": grade.score, "status": display_status, "has_unpublished_changes": changed,
        })
    coefficients = db.execute(
        select(GradeCoefficient, Team).join(Team, Team.id == GradeCoefficient.team_id)
        .where(GradeCoefficient.assignment_id == assignment_id).order_by(Team.name)
    ).all()
    groups = [{"team_id": str(team_item.id), "team_name": team_item.name, "draft_value": item.draft_value, "published_value": item.published_value, "version": item.version, "member_count": sum(row[0].coefficient_id == item.id for row in rows)} for item, team_item in coefficients]
    return {
        "assignment": {"id": str(assignment.id), "title": assignment.title, "campaign_status": campaign.status, "grades_generated_at": campaign.grades_generated_at},
        "groups": groups, "items": items, "total": len(items),
        "summary": {"publishable": sum(item["peer_score"] is not None and item["draft_score"] is not None for item in items), "pending": sum(item["peer_score"] is None for item in items), "changed": sum(item["has_unpublished_changes"] for item in items), "published": sum(item["score"] is not None for item in items)},
    }


@app.patch("/api/v1/grades/assignments/{assignment_id}/teams/{team_id}/coefficient")
def update_grade_coefficient(assignment_id: UUID, team_id: UUID, data: CoefficientIn, user: CsrfUser, db: Db):
    teacher(user); assignment, campaign = require_grade_assignment(db, user, assignment_id); require_writable_class(db, user, assignment.class_id)
    if campaign.grades_generated_at is None: raise ApiError(409, "GRADES_NOT_GENERATED", "互评结束后才能设置成绩系数")
    coefficient = db.scalar(select(GradeCoefficient).where(GradeCoefficient.assignment_id == assignment_id, GradeCoefficient.team_id == team_id).with_for_update())
    if not coefficient: raise ApiError(404, "GRADE_COEFFICIENT_NOT_FOUND", "该作业没有此小组的系数记录")
    if coefficient.version != data.version: raise ApiError(409, "GRADE_COEFFICIENT_VERSION_CONFLICT", "小组系数已被修改，请刷新后重试", {"current_version": coefficient.version})
    coefficient.draft_value, coefficient.updated_by, coefficient.version = data.coefficient, user.id, coefficient.version + 1
    grade_rows = db.scalars(select(Grade).where(Grade.coefficient_id == coefficient.id).with_for_update()).all()
    for grade in grade_rows:
        grade.draft_score = final_score(grade.peer_score, data.coefficient) if grade.peer_score is not None else None
        if grade.status != "PUBLISHED": grade.status = "DRAFT" if grade.draft_score is not None else "PENDING"
        grade.version += 1
    audit(db, user, "GRADE_COEFFICIENT_UPDATED", "assignment", str(assignment_id), {"team_id": str(team_id), "coefficient": str(data.coefficient)}); db.commit()
    return {"team_id": str(team_id), "draft_value": coefficient.draft_value, "published_value": coefficient.published_value, "version": coefficient.version}


@app.post("/api/v1/grades/assignments/{assignment_id}/publish")
def publish_assignment_grades(assignment_id: UUID, data: GradePublishIn, user: CsrfUser, db: Db):
    teacher(user); assignment, campaign = require_grade_assignment(db, user, assignment_id); require_writable_class(db, user, assignment.class_id)
    if campaign.grades_generated_at is None: raise ApiError(409, "GRADES_NOT_GENERATED", "互评结束后才能发布成绩")
    rows = db.execute(
        select(Grade, GradeCoefficient)
        .join(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
        .where(Grade.assignment_id == assignment_id, Grade.peer_score.is_not(None), Grade.draft_score.is_not(None))
        .with_for_update()
    ).all()
    changed = [(grade, coefficient) for grade, coefficient in rows if grade.status == "PUBLISHED" and grade.score != grade.draft_score]
    if changed and len(data.reason.strip()) < 2: raise ApiError(422, "GRADE_CHANGE_REASON_REQUIRED", "修改已发布成绩时必须填写原因")
    if not rows: raise ApiError(409, "NO_PUBLISHABLE_GRADES", "当前没有可发布的成绩")
    published = 0
    touched_coefficients = set()
    for grade, coefficient in rows:
        if grade.status == "PUBLISHED" and grade.score == grade.draft_score: continue
        if grade.status == "PUBLISHED":
            db.add(GradeRevision(grade_id=grade.id, changed_by=user.id, peer_score=grade.peer_score, coefficient=coefficient.published_value, score=grade.score, reason=data.reason.strip()))
        grade.score, grade.status, grade.version = grade.draft_score, "PUBLISHED", grade.version + 1
        touched_coefficients.add(coefficient.id)
        notify(db, grade.subject_user_id, "GRADE_PUBLISHED", f"成绩已发布：{assignment.title}")
        published += 1
    for coefficient in {item for _, item in rows if item.id in touched_coefficients}:
        coefficient.published_value = coefficient.draft_value
        coefficient.version += 1
    audit(db, user, "GRADES_PUBLISHED", "assignment", str(assignment_id), {"published": published, "reason": data.reason.strip()}); db.commit()
    pending = db.scalar(select(func.count()).select_from(Grade).where(Grade.assignment_id == assignment_id, or_(Grade.peer_score.is_(None), Grade.draft_score.is_(None)))) or 0
    return {"published": published, "pending": pending, "changed": len(changed)}


@app.get("/api/v1/grades/{gid}/revisions")
def grade_revisions(gid: UUID, user: CurrentUser, db: Db):
    teacher(user); grade = db.get(Grade, gid); assignment = db.get(Assignment, grade.assignment_id) if grade else None
    if not grade or not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "GRADE_NOT_FOUND", "成绩不存在")
    rows = db.scalars(select(GradeRevision).where(GradeRevision.grade_id == gid).order_by(GradeRevision.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "peer_score": item.peer_score, "coefficient": item.coefficient, "score": item.score, "reason": item.reason, "created_at": item.created_at} for item in rows]}


@app.get("/api/v1/notifications")
def notifications(user: CurrentUser, db: Db):
    items = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.kind != "SUBMISSION_RESUBMITTED").order_by(Notification.created_at.desc()).limit(100)).all()
    def link(item: Notification) -> str | None:
        if item.object_type == "team" and item.object_id: return f"/teams?team={item.object_id}"
        if item.object_type == "assignment" and item.object_id: return f"/assignments/{item.object_id}?tab=submission"
        return None
    return {"items": [{"id": str(x.id), "title": x.title, "kind": x.kind, "object_type": x.object_type, "object_id": x.object_id, "link": link(x), "read": bool(x.read_at), "created_at": x.created_at} for x in items], "unread": sum(not x.read_at for x in items)}


@app.post("/api/v1/notifications/read", status_code=204)
def read_notifications(user: CsrfUser, db: Db):
    db.execute(Notification.__table__.update().where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=now())); db.commit(); return Response(status_code=204)


@app.get("/api/v1/audit-logs")
def audit_logs(user: CurrentUser, db: Db, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), q: str | None = Query(None, max_length=100), semester: str | None = Query(None, max_length=40), class_id: UUID | None = None, actor_role: Literal["TEACHER", "STUDENT"] | None = None, actions: list[str] = Query(default=[]), object_types: list[str] = Query(default=[])):
    teacher(user)
    query = select(AuditLog, User).outerjoin(User)
    owned_classes = select(TeachingClass.id).where(TeachingClass.teacher_id == user.id)
    query = query.where(or_(AuditLog.class_id.in_(owned_classes), and_(AuditLog.class_id.is_(None), AuditLog.actor_id == user.id)))
    if semester: query = query.where(AuditLog.class_semester == semester)
    if class_id:
        course = db.get(TeachingClass, class_id)
        if not course or course.teacher_id != user.id: raise ApiError(404, "CLASS_NOT_FOUND", "教学班不存在")
        query = query.where(AuditLog.class_id == class_id)
    if actor_role: query = query.where(User.role == actor_role)
    term = (q or "").strip()
    if term:
        text_filter = or_(User.display_name.icontains(term, autoescape=True), AuditLog.ip_address.icontains(term, autoescape=True), AuditLog.class_semester.icontains(term, autoescape=True), AuditLog.class_name.icontains(term, autoescape=True), AuditLog.action.icontains(term, autoescape=True), AuditLog.object_type.icontains(term, autoescape=True), AuditLog.object_id.icontains(term, autoescape=True))
        if actions: text_filter = or_(text_filter, AuditLog.action.in_(actions))
        if object_types: text_filter = or_(text_filter, AuditLog.object_type.in_(object_types))
        query = query.where(text_filter)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": str(x.id), "actor": p.display_name if p else "系统", "actor_role": p.role if p else "SYSTEM", "class_id": str(x.class_id) if x.class_id else None, "class_semester": x.class_semester, "class_name": x.class_name, "ip_address": x.ip_address, "action": x.action, "object_type": x.object_type, "object_id": x.object_id, "changes": x.changes, "created_at": x.created_at} for x, p in rows], "page": page, "page_size": page_size, "total": total}


def export_rows(kind: str, class_id: UUID, user: User, db: Session, assignment_id: UUID | None = None) -> list[list]:
    rows: list[list] = []
    state_labels = {"ACTIVE": "正常", "ARCHIVED": "已归档", "LEFT": "已退出", "DISBANDED": "已解散", "PUBLISHED": "已发布", "DRAFT": "草稿", "CLOSED": "已结束", "VALID": "有效", "INVALID": "已作废"}
    if kind == "members":
        rows.append(["学号", "姓名", "状态", "小组"])
        for member, person in db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == class_id)):
            team = membership(db, class_id, person.id)
            rows.append([person.login_name, person.display_name, state_labels.get(member.status, member.status), team[1].name if team else ""])
    elif kind == "teams":
        rows.append(["小组", "组长", "人数", "选题", "状态"])
        for team in db.scalars(select(Team).where(Team.class_id == class_id)):
            item = team_json(db, team, user); rows.append([item["name"], item["leader_name"], item["member_count"], item["topic"]["name"] if item["topic"] else "", state_labels.get(item["status"], item["status"])])
    elif kind == "grades":
        if assignment_id is None: raise ApiError(422, "ASSIGNMENT_REQUIRED", "导出成绩时必须选择单次作业")
        assignment = db.get(Assignment, assignment_id)
        if not assignment or assignment.class_id != class_id: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
        has_current_assessments = bool(db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.assignment_id == assignment_id).limit(1)))
        legacy_grades = db.scalars(select(Grade).where(Grade.assignment_id == assignment_id)).all()
        if legacy_grades and not has_current_assessments:
            rows.append(["作业", "学号", "姓名", "小组", "互评分", "小组系数", "最终分", "状态"])
            grade_rows = db.execute(
                select(Grade, User, GradeCoefficient, Team)
                .join(User, User.id == Grade.subject_user_id)
                .outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
                .outerjoin(Team, Team.id == GradeCoefficient.team_id)
                .where(Grade.assignment_id == assignment_id)
                .order_by(Team.name, User.login_name)
            ).all()
            for grade, person, coefficient, team_item in grade_rows:
                if grade.peer_score is None: status = "待处理"
                elif not coefficient or coefficient.draft_value is None: status = "待填系数"
                elif grade.status == "PUBLISHED" and grade.draft_score != grade.score: status = "有未发布修改"
                elif grade.status == "PUBLISHED": status = "已发布"
                else: status = "待发布"
                rows.append([assignment.title, person.login_name, person.display_name, team_item.name if team_item else "未分组", grade.peer_score, coefficient.draft_value if coefficient else None, grade.draft_score, status])
        else:
            rows.append(["作业", "学号", "姓名", "小组", "提交状态", "学生互评等级", "教师等级", "最终等级", "成绩来源", "评分状态"])
            people = db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT").order_by(User.login_name)).all()
            for _, person in people:
                team_row = membership(db, class_id, person.id)
                submitted = latest_personal_submission(db, assignment.id, person.id)
                if not submitted:
                    result = missing_submission_grade_result(assignment)
                    rows.append([assignment.title, person.login_name, person.display_name, team_row[1].name if team_row else "未分组", "未提交", "", "", result["final_grade"] or "", "系统判定" if result["grade_source"] == "SYSTEM" else "", "已评分" if result["final_grade"] else "未评分"])
                    continue
                _, version = submitted
                result = displayed_submission_grade_result(db, version)
                rows.append([
                    assignment.title, person.login_name, person.display_name, team_row[1].name if team_row else "未分组", "已提交",
                    result["peer_grade"] or "", result["teacher_grade"]["grade"] if result["teacher_grade"] else "", result["final_grade"] or "",
                    "教师评分" if result["grade_source"] == "TEACHER" else "学生互评" if result["grade_source"] == "PEER" else "",
                    "已评分" if result["final_grade"] else "待评分",
                ])
    else:
        rows.append(["作业", "评价人", "被评价人", "评价结果", "状态", "评语", "评价时间"])
        current_assignment_ids = set()
        direct_reviews = db.execute(select(SubmissionAssessment, Assignment).join(Assignment, Assignment.id == SubmissionAssessment.assignment_id).where(Assignment.class_id == class_id, SubmissionAssessment.kind == "PEER").order_by(SubmissionAssessment.updated_at.desc())).all()
        for review, assignment in direct_reviews:
            current_assignment_ids.add(assignment.id)
            rows.append([assignment.title, db.get(User, review.evaluator_id).display_name, db.get(User, review.subject_user_id).display_name, review.grade, state_labels.get(review.status, review.status), review.comment, review.published_at or review.updated_at])
        for review, assignment in db.execute(select(PeerReview, Assignment).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment).where(ReviewCampaign.class_id == class_id)):
            if assignment.id in current_assignment_ids: continue
            rows.append([assignment.title, db.get(User, review.reviewer_id).display_name, db.get(User, review.reviewee_id).display_name, review.total_score, state_labels.get(review.status, review.status), review.comment, review.updated_at])
    return rows


def export_cell(value):
    if isinstance(value, datetime):
        localized = value.astimezone(ZoneInfo("Asia/Shanghai")) if value.tzinfo else value
        return localized.strftime("%Y-%m-%d %H:%M:%S")
    return value


@app.get("/api/v1/exports/{kind}.csv")
def export_csv(kind: Literal["members", "teams", "grades", "reviews"], user: CurrentUser, db: Db, class_id: UUID = Query(), assignment_id: UUID | None = Query(None)):
    teacher(user); require_class(db, user, class_id); out = io.StringIO(); writer = csv.writer(out); writer.writerows([[export_cell(value) for value in row] for row in export_rows(kind, class_id, user, db, assignment_id)])
    suffix = f"-{assignment_id}" if kind == "grades" else ""
    return PlainTextResponse("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{kind}{suffix}.csv"'})


@app.get("/api/v1/exports/{kind}.xlsx")
def export_xlsx(kind: Literal["members", "teams", "grades", "reviews"], user: CurrentUser, db: Db, class_id: UUID = Query(), assignment_id: UUID | None = Query(None)):
    teacher(user); require_class(db, user, class_id); workbook = Workbook(); sheet = workbook.active; sheet.title = "导出数据"
    for row in export_rows(kind, class_id, user, db, assignment_id): sheet.append([export_cell(value) for value in row])
    suffix = f"-{assignment_id}" if kind == "grades" else ""
    buffer = io.BytesIO(); workbook.save(buffer); buffer.seek(0)
    return Response(content=buffer.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": content_disposition(f"{kind}{suffix}.xlsx")})


@app.patch("/api/v1/classes/{cid}")
def update_class(cid: UUID, data: ClassUpdateIn, user: CsrfUser, db: Db):
    teacher(user)
    course = db.scalar(select(TeachingClass).where(TeachingClass.id == cid, TeachingClass.teacher_id == user.id).with_for_update())
    if not course: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可管理的教学班")
    if course.version != data.version: raise ApiError(409, "CLASS_VERSION_CONFLICT", "教学班已被修改，请刷新后重试", {"current_version": course.version})
    metadata_fields = {"semester", "name", "team_deadline", "topic_public", "invite_requires_approval"} & data.model_fields_set
    if course.status == "ARCHIVED" and metadata_fields: raise ApiError(409, "CLASS_ARCHIVED", "请先恢复教学班再编辑资料")
    changes = {}
    for field in ("semester", "name"):
        value = getattr(data, field)
        if value is not None:
            value = value.strip()
            if value != getattr(course, field): changes[field] = {"from": getattr(course, field), "to": value}; setattr(course, field, value)
    if "team_deadline" in data.model_fields_set and data.team_deadline != course.team_deadline:
        changes["team_deadline"] = {"from": course.team_deadline.isoformat() if course.team_deadline else None, "to": data.team_deadline.isoformat() if data.team_deadline else None}
        course.team_deadline = data.team_deadline
    for field in ("topic_public", "invite_requires_approval"):
        value = getattr(data, field)
        if value is not None and value != getattr(course, field):
            changes[field] = {"from": getattr(course, field), "to": value}; setattr(course, field, value)
    if data.status is not None and data.status != course.status:
        changes["status"] = {"from": course.status, "to": data.status}; course.status = data.status
    if changes:
        course.version += 1; audit(db, user, "CLASS_UPDATED", "class", str(cid), changes); db.commit()
    return class_json(course)


@app.delete("/api/v1/classes/{cid}", status_code=204)
def delete_class(cid: UUID, user: CsrfUser, db: Db):
    teacher(user)
    course = db.scalar(select(TeachingClass).where(TeachingClass.id == cid, TeachingClass.teacher_id == user.id).with_for_update())
    if not course: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可管理的教学班")
    blockers = {
        "members": db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.class_id == cid)) or 0,
        "imports": db.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.class_id == cid)) or 0,
        "teams": db.scalar(select(func.count()).select_from(Team).where(Team.class_id == cid)) or 0,
        "assignments": db.scalar(select(func.count()).select_from(Assignment).where(Assignment.class_id == cid)) or 0,
    }
    if any(blockers.values()): raise ApiError(409, "CLASS_NOT_EMPTY", "教学班已有历史数据，请改用归档", blockers)
    audit(db, user, "CLASS_DELETED", "class", str(cid), {"semester": course.semester, "name": course.name})
    db.execute(delete(ClassJoinRequest).where(ClassJoinRequest.class_id == cid))
    db.delete(course); db.commit(); return Response(status_code=204)


@app.post("/api/v1/teams/{tid}/invitations", status_code=201)
def invite_member(tid: UUID, data: InviteIn, user: CsrfUser, db: Db):
    team = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not team or team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可邀请成员")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    if team.status != "ACTIVE" or not team.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组已截止招募，不能邀请成员")
    target = db.get(User, data.student_id)
    if not target or not db.scalar(select(ClassMember).where(ClassMember.class_id == team.class_id, ClassMember.user_id == target.id, ClassMember.status == "ACTIVE")): raise ApiError(404, "MEMBER_NOT_FOUND", "学生不在当前教学班")
    if membership(db, team.class_id, target.id): raise ApiError(409, "ALREADY_IN_TEAM", "该学生已经加入小组")
    exists = db.scalar(select(TeamRequest).where(TeamRequest.team_id == tid, TeamRequest.applicant_id == target.id, TeamRequest.kind == "INVITATION", TeamRequest.status == "PENDING"))
    if exists: raise ApiError(409, "INVITATION_EXISTS", "已邀请该学生")
    req = TeamRequest(class_id=team.class_id, team_id=tid, applicant_id=target.id, inviter_id=user.id, kind="INVITATION", expires_at=now() + timedelta(days=7)); db.add(req); notify(db, target.id, "TEAM_INVITATION", f"邀请你加入「{team.name}」"); db.commit(); return {"id": str(req.id), "status": req.status}


@app.post("/api/v1/team-requests/{rid}/respond")
def respond_invitation(rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    req = db.scalar(select(TeamRequest).where(TeamRequest.id == rid).with_for_update()); team = db.scalar(select(Team).where(Team.id == req.team_id).with_for_update()) if req else None
    if not req or req.kind != "INVITATION" or req.applicant_id != user.id or req.status != "PENDING": raise ApiError(409, "INVITATION_NOT_PENDING", "邀请已处理")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    if req.expires_at and req.expires_at < now(): req.status = "EXPIRED"; db.commit(); raise ApiError(409, "INVITATION_EXPIRED", "邀请已过期")
    if decision == "APPROVED":
        if not team or team.status != "ACTIVE" or not team.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组已截止招募，不能加入")
        if membership(db, req.class_id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
        db.add(TeamMember(team_id=team.id, class_id=req.class_id, user_id=user.id)); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == req.class_id, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); req.status = "APPROVED"
    else: req.status = "REJECTED"
    req.resolved_at = now(); audit(db, user, "TEAM_INVITATION_RESPONDED", "team_request", str(req.id), {"decision": decision}); db.commit(); return {"id": str(req.id), "status": req.status}


@app.post("/api/v1/teams/{tid}/transfer")
def transfer_leader(tid: UUID, data: TransferIn, user: CsrfUser, db: Db):
    team = db.get(Team, tid)
    if not team or team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可移交")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    old = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == user.id, TeamMember.status == "ACTIVE")); new = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == data.new_leader_id, TeamMember.status == "ACTIVE"))
    if not new: raise ApiError(422, "NEW_LEADER_INVALID", "新组长必须是当前组员")
    team.leader_id, old.role, new.role, team.version = data.new_leader_id, "MEMBER", "LEADER", team.version + 1; audit(db, user, "TEAM_LEADER_TRANSFERRED", "team", str(tid)); db.commit(); return team_json(db, team, user)


@app.post("/api/v1/teams/{tid}/leave", status_code=204)
def leave_team(tid: UUID, user: CsrfUser, db: Db):
    team = db.get(Team, tid); member = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == user.id, TeamMember.status == "ACTIVE"))
    if not team or not member: raise ApiError(404, "TEAM_MEMBERSHIP_NOT_FOUND", "不在该小组")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    if team.leader_id == user.id: raise ApiError(409, "LEADER_TRANSFER_REQUIRED", "组长退出前必须移交组长")
    member.status = "LEFT"; audit(db, user, "TEAM_LEFT", "team", str(tid)); db.commit(); return Response(status_code=204)


@app.delete("/api/v1/teams/{tid}", status_code=204)
def disband_team(tid: UUID, user: CsrfUser, db: Db):
    team = db.scalar(select(Team).where(Team.id == tid, Team.status == "ACTIVE").with_for_update())
    if not team: raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    if user.role == "TEACHER":
        require_writable_class(db, user, team.class_id)
    elif team.leader_id == user.id:
        course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    else:
        raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长或任课教师可解散小组")
    team.status = "DISBANDED"; db.execute(TeamMember.__table__.update().where(TeamMember.team_id == tid, TeamMember.status == "ACTIVE").values(status="LEFT")); db.execute(TeamRequest.__table__.update().where(TeamRequest.team_id == tid, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); audit(db, user, "TEAM_DISBANDED", "team", str(tid)); db.commit(); return Response(status_code=204)


@app.delete("/api/v1/teams/{tid}/members/{uid}", status_code=204)
def teacher_remove_team_member(tid: UUID, uid: UUID, user: CsrfUser, db: Db):
    teacher(user); team = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not team or not user_class(db, user, team.class_id): raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    require_writable_class(db, user, team.class_id)
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == uid, TeamMember.status == "ACTIVE").with_for_update())
    if not member: raise ApiError(404, "TEAM_MEMBERSHIP_NOT_FOUND", "该学生不在小组中")
    member.status = "REMOVED"
    if team.leader_id == uid:
        replacement = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id != uid, TeamMember.status == "ACTIVE").order_by(TeamMember.joined_at).limit(1))
        if replacement:
            replacement.role = "LEADER"; team.leader_id = replacement.user_id
        else:
            team.status = "DISBANDED"
    team.version += 1; notify(db, uid, "TEAM_MEMBER_REMOVED", f"教师已将你移出小组「{team.name}」")
    audit(db, user, "TEAM_MEMBER_REMOVED", "team", str(tid), {"user_id": str(uid)}); db.commit(); return Response(status_code=204)


@app.post("/api/v1/topics/{topic_id}/decision")
def topic_decision(topic_id: UUID, decision: Literal["APPROVED", "REJECTED"], data: ReasonIn, user: CsrfUser, db: Db):
    teacher(user); topic = db.get(Topic, topic_id)
    if not topic or not user_class(db, user, topic.class_id): raise ApiError(404, "TOPIC_NOT_FOUND", "选题不存在")
    require_writable_class(db, user, topic.class_id)
    reason = (data.reason or "").strip()
    if decision == "REJECTED" and not reason: raise ApiError(422, "TOPIC_REASON_REQUIRED", "驳回选题时必须填写原因")
    if decision == "APPROVED" and not reason: reason = "审核通过"
    topic.review_status, topic.review_reason = decision, reason
    decision_label = "已通过" if decision == "APPROVED" else "已驳回"
    for member in db.scalars(select(TeamMember).where(TeamMember.team_id == topic.team_id, TeamMember.status == "ACTIVE")): notify(db, member.user_id, "TOPIC_DECISION", f"选题审核结果：{decision_label}")
    audit(db, user, "TOPIC_DECIDED", "topic", str(topic.id), {"decision": decision, "reason": reason}); db.commit(); return {"id": str(topic.id), "status": topic.review_status, "reason": topic.review_reason}


@app.get("/api/v1/assignments/{aid}/submissions")
def submission_board(aid: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    rows = list(db.scalars(select(Submission).where(Submission.assignment_id == aid)).all())
    by_owner = {str(row.owner_user_id or row.owner_team_id): row for row in rows}
    submissions_by_id = {row.id: row for row in rows}
    if assignment.submitter_type == "INDIVIDUAL":
        owner_rows = db.execute(
            select(ClassMember, User, Team)
            .join(User, User.id == ClassMember.user_id)
            .outerjoin(TeamMember, and_(
                TeamMember.class_id == ClassMember.class_id,
                TeamMember.user_id == ClassMember.user_id,
                TeamMember.status == "ACTIVE",
            ))
            .outerjoin(Team, and_(Team.id == TeamMember.team_id, Team.status == "ACTIVE"))
            .where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")
            .order_by(User.login_name)
        ).all()
        owners = [
            (member.user_id, person.display_name, person.login_name, team.id if team else None, team.name if team else None)
            for member, person, team in owner_rows
        ]
    else:
        owners = [(team.id, team.name, None, team.id, team.name) for team in db.scalars(select(Team).where(Team.class_id == assignment.class_id, Team.status == "ACTIVE").order_by(Team.name)).all()]

    versions = list(db.scalars(
        select(SubmissionVersion)
        .join(Submission, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(Submission.assignment_id == aid)
    ).all()) if rows else []
    versions_by_submission = {version.submission_id: version for version in versions}
    submitted_versions = [
        version for version in versions
        if submissions_by_id[version.submission_id].status == "SUBMITTED"
    ]
    submitted_version_ids = [version.id for version in submitted_versions]

    files_by_version: dict[UUID, list[FileObject]] = {}
    if submitted_version_ids:
        for version_id, file in db.execute(
            select(VersionFile.version_id, FileObject)
            .join(FileObject, FileObject.id == VersionFile.file_id)
            .where(VersionFile.version_id.in_(submitted_version_ids))
        ):
            files_by_version.setdefault(version_id, []).append(file)

    assessments_by_version: dict[UUID, list[SubmissionAssessment]] = {}
    assessments = list(db.scalars(
        select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id.in_(submitted_version_ids))
    ).all()) if submitted_version_ids else []
    for assessment in assessments:
        assessments_by_version.setdefault(assessment.submission_version_id, []).append(assessment)

    evaluator_names = dict(db.execute(
        select(User.id, User.display_name).where(User.id.in_({item.evaluator_id for item in assessments}))
    ).all()) if assessments else {}
    annotations_by_assessment: dict[UUID, list[dict]] = {}
    if assessments:
        assessment_ids = [item.id for item in assessments]
        annotations = db.scalars(
            select(SubmissionAnnotation)
            .where(SubmissionAnnotation.assessment_id.in_(assessment_ids))
            .order_by(SubmissionAnnotation.position, SubmissionAnnotation.created_at)
        ).all()
        for annotation in annotations:
            annotations_by_assessment.setdefault(annotation.assessment_id, []).append(annotation_json(annotation))

    def serialize_assessment(item: SubmissionAssessment) -> dict:
        return assessment_payload(item, evaluator_names[item.evaluator_id], annotations_by_assessment.get(item.id, []))

    items = []
    for owner_id, owner_name, student_no, team_id, team_name in owners:
        submission = by_owner.get(str(owner_id))
        latest = versions_by_submission.get(submission.id) if submission else None
        files = files_by_version.get(latest.id, []) if latest and submission.status == "SUBMITTED" else []
        grade_result = build_submission_grade_result(assessments_by_version.get(latest.id, []), serialize_assessment) if latest and submission.status == "SUBMITTED" else missing_submission_grade_result(assignment)
        if latest and submission.status == "SUBMITTED" and not grade_result.get("final_grade") and latest.version_no > 1:
            grade_result = displayed_submission_grade_result(db, latest, grade_result)
        items.append({"id": str(submission.id) if submission else str(owner_id), "submission_version_id": str(latest.id) if latest and submission.status == "SUBMITTED" else None, "submission_version_no": latest.version_no if latest and submission.status == "SUBMITTED" else None, "grade_cap": latest.grade_cap if latest and submission.status == "SUBMITTED" else None, "user_id": str(owner_id) if assignment.submitter_type == "INDIVIDUAL" else None, "owner": owner_name, "student_no": student_no, "team_id": str(team_id) if team_id else None, "team_name": team_name, "status": submission.status if submission else "NOT_SUBMITTED", "submitted_at": latest.submitted_at if latest and submission.status == "SUBMITTED" else None, "is_late": latest.is_late if latest and submission.status == "SUBMITTED" else False, "member_snapshot": latest.member_snapshot if latest else {}, "files": [file_json(file) for file in files], **grade_result})
    return {"items": items, "total": len(items)}


@app.post("/api/v1/review-campaigns/{cid}/close")
def close_campaign(cid: UUID, user: CsrfUser, db: Db):
    teacher(user); campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == cid).with_for_update())
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_writable_class(db, user, campaign.class_id)
    if campaign.status == "CLOSED":
        if campaign.grades_generated_at is None:
            finalize_campaign(db, campaign, now())
            db.commit()
        return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "due_at": campaign.due_at, "status": campaign.status, "grades_generated_at": campaign.grades_generated_at, "version": campaign.version}
    if campaign.status != "ACTIVE": raise ApiError(409, "CAMPAIGN_NOT_ACTIVE", "当前互评活动不能提前截止")
    campaign.due_at = now()
    finalize_campaign(db, campaign, campaign.due_at)
    audit(db, user, "REVIEW_CAMPAIGN_CLOSED", "review_campaign", str(cid), {"due_at": campaign.due_at.isoformat()})
    db.commit()
    return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "due_at": campaign.due_at, "status": campaign.status, "grades_generated_at": campaign.grades_generated_at, "version": campaign.version}


@app.get("/api/v1/files/{fid}/preview")
def preview_file(fid: UUID, user: CurrentUser, db: Db):
    file = require_file_access(db, user, fid)
    suffix = Path(file.storage_path).suffix.lower()
    if suffix == ".md":
        try: source = decode_text_file(storage.get_object_bytes(file.storage_path))
        except UnicodeDecodeError: raise ApiError(422, "MARKDOWN_ENCODING_INVALID", "Markdown 文件编码无法识别")
        return PlainTextResponse(source, media_type="text/markdown; charset=utf-8")
    if suffix in {".docx", ".pptx", ".xlsx"}:
        # Preview endpoints must render in the browser; the download endpoint keeps
        # the original filename and attachment disposition.
        return download(fid, user, db)
    try:
        stream = storage.get_object_stream(file.storage_path)
    except NoSuchKey:
        raise ApiError(404, "FILE_MISSING", "文件存储不可用")
    return StreamingResponse(stream, media_type=file.detected_mime, headers={"Content-Disposition": "inline"})


@app.get("/api/v1/files/{fid}/preview-url")
def preview_file_url(fid: UUID, user: CurrentUser, db: Db):
    file = require_file_access(db, user, fid)
    if Path(file.storage_path).suffix.lower() != ".md":
        raise ApiError(422, "FILE_PREVIEW_TYPE_INVALID", "仅 Markdown 文件支持前端直接预览")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    params = {"response-content-disposition": content_disposition(file.original_name, "inline")}
    return {"url": storage.sign_get_url(file.storage_path, expires, params), "expires_in": expires}


@app.get("/api/v1/files/{fid}/render")
def render_file(fid: UUID, user: CurrentUser, db: Db):
    require_file_access(db, user, fid)
    raise ApiError(410, "FILE_RENDER_REMOVED", "Markdown 文件请使用前端预览")


@app.get("/api/v1/assignments/{aid}/download.zip")
def download_submissions(aid: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    rows = db.execute(
        select(Submission, SubmissionVersion)
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(Submission.assignment_id == aid, Submission.status == "SUBMITTED")
    ).all()
    version_ids = [version.id for _, version in rows]
    files_by_version: dict[UUID, list[FileObject]] = {}
    if version_ids:
        for version_id, file in db.execute(select(VersionFile.version_id, FileObject).join(FileObject, FileObject.id == VersionFile.file_id).where(VersionFile.version_id.in_(version_ids))):
            files_by_version.setdefault(version_id, []).append(file)
    user_ids = {submission.owner_user_id for submission, _ in rows if submission.owner_user_id}
    team_ids = {submission.owner_team_id for submission, _ in rows if submission.owner_team_id}
    users = {item.id: item for item in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    teams = {item.id: item for item in db.scalars(select(Team).where(Team.id.in_(team_ids))).all()} if team_ids else {}
    archive = TemporaryFile()
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for submission, version in rows:
                owner = users.get(submission.owner_user_id) if submission.owner_user_id else teams.get(submission.owner_team_id)
                owner_name = owner.login_name if isinstance(owner, User) else owner.name
                for file in files_by_version.get(version.id, []):
                    with bundle.open(f"{owner_name}/{file.original_name}", "w") as dest:
                        for chunk in storage.get_object_stream(file.storage_path):
                            dest.write(chunk)
        archive.seek(0)
    except Exception:
        archive.close()
        raise
    audit(db, user, "SUBMISSIONS_EXPORTED", "assignment", str(aid)); db.commit()

    def chunks():
        try:
            while chunk := archive.read(1024 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(chunks(), media_type="application/zip", headers={"Content-Disposition": content_disposition(f"{assignment.title}.zip")})


@app.get("/api/v1/teams/{tid}/coursework.zip")
def download_team_coursework(tid: UUID, user: CurrentUser, db: Db):
    teacher(user)
    team_item = db.get(Team, tid)
    if not team_item or team_item.status != "ACTIVE" or not user_class(db, user, team_item.class_id):
        raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")

    assignments = db.scalars(select(Assignment).where(
        Assignment.class_id == team_item.class_id,
        Assignment.submitter_type == "TEAM",
        Assignment.status.in_(["PUBLISHED", "CLOSED"]),
    ).order_by(Assignment.due_at.desc())).all()
    if not assignments:
        raise ApiError(409, "NO_COURSEWORK_TO_EXPORT", "暂无作业可导出")

    assignment_ids = [assignment.id for assignment in assignments]
    submissions = {
        submission.assignment_id: submission
        for submission in db.scalars(select(Submission).where(Submission.assignment_id.in_(assignment_ids), Submission.owner_team_id == tid)).all()
    }
    submitted = [submission for submission in submissions.values() if submission.status == "SUBMITTED"]
    current_versions = {submission.id: submission.current_version_no for submission in submitted}
    versions = {
        version.submission_id: version
        for version in db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id.in_(current_versions))).all()
        if version.version_no == current_versions[version.submission_id]
    } if submitted else {}
    files_by_version: dict[UUID, list[FileObject]] = {}
    if versions:
        for version_id, file in db.execute(
            select(VersionFile.version_id, FileObject)
            .join(FileObject, FileObject.id == VersionFile.file_id)
            .where(VersionFile.version_id.in_([version.id for version in versions.values()]))
        ):
            files_by_version.setdefault(version_id, []).append(file)

    def csv_bytes(rows):
        output = io.StringIO()
        csv.writer(output).writerows([[export_cell(value) for value in row] for row in rows])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    homework_rows = [["作业", "截止时间", "提交状态", "提交时间", "是否迟交", "附件数"]]
    archive_file = TemporaryFile()
    try:
        with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for assignment in assignments:
                submission = submissions.get(assignment.id)
                version = versions.get(submission.id) if submission else None
                files = files_by_version.get(version.id, []) if version else []
                homework_rows.append([assignment.title, assignment.due_at, "已提交" if version else "未提交", version.submitted_at if version else None, "是" if version and version.is_late else "否", len(files)])
                for file in files:
                    with archive.open(f"小组作业/{assignment.id}/{file.id}-{Path(file.original_name).name}", "w") as dest:
                        for chunk in storage.get_object_stream(file.storage_path):
                            dest.write(chunk)
            archive.writestr("小组作业提交记录.csv", csv_bytes(homework_rows))

            grade_rows = [["作业", "提交状态", "学生互评等级", "教师等级", "最终等级", "成绩来源", "评分状态"]]
            for assignment in assignments:
                submission = submissions.get(assignment.id)
                version = versions.get(submission.id) if submission else None
                result = displayed_submission_grade_result(db, version) if version else missing_submission_grade_result(assignment)
                source = result["grade_source"]
                grade_rows.append([
                    assignment.title, "已提交" if version else "未提交", result["peer_grade"],
                    result["teacher_grade"]["grade"] if result["teacher_grade"] else None,
                    result["final_grade"], {"TEACHER": "教师评分", "PEER": "学生互评", "SYSTEM": "系统判定"}.get(source, ""),
                    "已评分" if result["final_grade"] else "待评分",
                ])
            archive.writestr("小组作业成绩表.csv", csv_bytes(grade_rows))

        archive_file.seek(0)
        def stream():
            try:
                while chunk := archive_file.read(1024 * 1024):
                    yield chunk
            finally:
                archive_file.close()
        return StreamingResponse(stream(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="team-{tid}-coursework.zip"'})
    except Exception:
        archive_file.close()
        raise


@app.get("/api/v1/review-campaigns/{cid}/stats")
def campaign_stats(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); campaign = db.get(ReviewCampaign, cid)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    reviews = db.scalars(select(PeerReview).where(PeerReview.campaign_id == cid, PeerReview.status == "VALID")).all()
    if campaign.assignment_snapshot_at is not None:
        allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == cid)).all()
        skipped_allocations = [item for item in allocations if item.status == "SKIPPED"]
        reviewer_names = {
            item.id: item.display_name
            for item in db.scalars(select(User).where(User.id.in_([allocation.reviewer_id for allocation in skipped_allocations]))).all()
        } if skipped_allocations else {}
        skipped = [{"reviewer_id": str(x.reviewer_id), "reviewer_name": reviewer_names.get(x.reviewer_id, ""), "reason": x.skip_reason} for x in skipped_allocations]
        assigned = sum(x.status != "SKIPPED" for x in allocations)
        completed = sum(x.status == "COMPLETED" for x in allocations)
        return {"assigned_count": assigned, "completed_count": completed, "skipped_count": len(skipped), "skipped": skipped, "completion_rate": round(completed * 100 / assigned, 1) if assigned else 0, "review_count": len(reviews), "reviewer_count": completed, "uncompleted_reviewer_count": max(assigned - completed, 0), "average_score": round(sum(x.total_score for x in reviews) / len(reviews), 2) if reviews else None, "received_count": {str(x.reviewee_id): 1 for x in reviews}}
    reviewers = len({x.reviewer_id for x in reviews}); received_count = {}
    for x in reviews: received_count[str(x.reviewee_id)] = received_count.get(str(x.reviewee_id), 0) + 1
    grouped = {}
    for member in db.scalars(select(TeamMember).join(Team).where(Team.class_id == campaign.class_id, Team.status == "ACTIVE", TeamMember.status == "ACTIVE")):
        grouped.setdefault(member.team_id, []).append(member.user_id)
    eligible_reviewers = sum(len(member_ids) for member_ids in grouped.values() if len(member_ids) > 1)
    return {"review_count": len(reviews), "reviewer_count": reviewers, "uncompleted_reviewer_count": max(eligible_reviewers - reviewers, 0), "average_score": round(sum(x.total_score for x in reviews) / len(reviews), 2) if reviews else None, "received_count": received_count}


@app.api_route("/{full_path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
def serve_frontend(request: Request, full_path: str):
    if request.method not in {"GET", "HEAD"}:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    dist = settings.frontend_dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    requested = (dist / full_path).resolve()
    if requested.is_relative_to(dist) and requested.is_file():
        if requested == index:
            cache_control = "no-cache"
        elif full_path.startswith("assets/"):
            cache_control = "public, max-age=31536000, immutable"
        else:
            cache_control = "public, max-age=3600"
        return FileResponse(requested, headers={"Cache-Control": cache_control})

    first_segment = full_path.split("/", 1)[0]
    if first_segment in {"api", "health", "assets"} or Path(full_path).suffix:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
