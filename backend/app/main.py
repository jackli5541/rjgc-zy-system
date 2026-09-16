from __future__ import annotations

import csv, html, io, mimetypes, os, re, secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import Cookie, Depends, FastAPI, File, Header, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
import bleach
import markdown
import zipfile
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import Assignment, AuditLog, BackgroundJob, ClassJoinRequest, ClassMember, FileObject, Grade, GradeRevision, ImportBatch, LoginSession, Notification, PeerReview, ReviewAssignment, ReviewCampaign, Submission, SubmissionVersion, TeachingClass, Team, TeamMember, TeamRequest, Topic, User, VersionFile
from app.security import hash_password, new_session, token_hash, verify_password
from app.settings import settings

app = FastAPI(title="软件工程作业系统 API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SAFE_HTML_TAGS = ["p", "br", "h1", "h2", "h3", "h4", "strong", "em", "s", "ul", "ol", "li", "blockquote", "pre", "code", "a"]
SAFE_HTML_ATTRIBUTES = {"a": ["href", "title", "target", "rel"]}


def clean_html(value: str) -> str:
    return bleach.clean(value, tags=SAFE_HTML_TAGS, attributes=SAFE_HTML_ATTRIBUTES, protocols=["http", "https", "mailto"], strip=True)


def render_description(value: str) -> str:
    if re.search(r"</?[a-zA-Z][^>]*>", value):
        return clean_html(value)
    return html.escape(value).replace("\n", "<br>")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(ApiError)
async def api_error(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, "details": exc.details, "request_id": request.state.request_id})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(x) for x in item["loc"] if x != "body"), "message": item["msg"]} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "提交内容不完整或格式不正确", "details": {"fields": details}, "request_id": request.state.request_id})


Db = Annotated[Session, Depends(get_db)]


def now() -> datetime: return datetime.now(UTC)


def audit(db: Session, user: User | None, action: str, kind: str, oid: str, changes: dict | None = None):
    db.add(AuditLog(actor_id=user.id if user else None, action=action, object_type=kind, object_id=oid, changes=changes or {}))


def notify(db: Session, uid: UUID, kind: str, title: str, object_type: str | None = None, object_id: str | None = None):
    db.add(Notification(user_id=uid, kind=kind, title=title, object_type=object_type, object_id=object_id))


def current_user(session_id: Annotated[str | None, Cookie()] = None, db: Session = Depends(get_db)) -> User:
    if not session_id: raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id), LoginSession.revoked_at.is_(None), LoginSession.expires_at > now()))
    user = db.get(User, session.user_id) if session else None
    if not user or user.status != "ACTIVE": raise ApiError(401, "SESSION_INVALID", "会话已失效")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


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
    item = {"id": str(x.id), "course": x.course, "semester": x.semester, "name": x.name, "invite_code": x.invite_code, "status": x.status, "team_deadline": x.team_deadline, "max_team_members": x.max_team_members, "topic_public": x.topic_public, "invite_requires_approval": x.invite_requires_approval, "version": x.version}
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
    return {"id": str(x.id), "name": x.name, "leader_id": str(x.leader_id), "leader_name": leader.display_name, "member_count": count, "max_members": x.max_members, "open_recruitment": x.open_recruitment, "status": x.status, "is_leader": x.leader_id == viewer.id, "pending_count": pending, "topic": None if not topic or not can_view_topic else {"id": str(topic.id), "name": topic.name, "description": topic.description, "status": topic.review_status, "reason": topic.review_reason}, "version": x.version}


class LoginIn(BaseModel):
    account: str; password: str; role: Literal["teacher", "student"] | None = None
class ClassIn(BaseModel):
    semester: str = Field(min_length=2, max_length=40); name: str = Field(min_length=2, max_length=100); max_team_members: int = Field(5, ge=2, le=20); team_deadline: datetime | None = None; topic_public: bool = False; invite_requires_approval: bool = True
class TeamIn(BaseModel):
    class_id: UUID; name: str = Field(min_length=2, max_length=40); open_recruitment: bool = True
class TopicIn(BaseModel):
    name: str = Field(min_length=2, max_length=100); description: str = Field("", max_length=1000)
class AssignmentFields(BaseModel):
    title: str = Field(min_length=2, max_length=100); description: str = Field(min_length=1, max_length=5000); submitter_type: Literal["TEAM", "INDIVIDUAL"]; starts_at: datetime | None = None; due_at: datetime; allow_late: bool = False; publish: bool = True
    auto_review_enabled: bool = False
    auto_review_mode: Literal["TEAM", "CLASS"] | None = None
    auto_review_criteria_text: str = Field("", max_length=5000)
    auto_review_due_at: datetime | None = None
class AssignmentIn(AssignmentFields):
    class_id: UUID
class AssignmentBulkIn(AssignmentFields):
    class_ids: list[UUID] = Field(min_length=1)
class CampaignFields(BaseModel):
    rubric: list[dict] = Field(min_length=1, max_length=10); comment_min_length: int = Field(20, ge=0, le=1000); due_at: datetime; publish_at: datetime | None = None; require_all: bool = False; allow_update: bool = True
class CampaignIn(CampaignFields):
    assignment_id: UUID
class AllocatedCampaignIn(BaseModel):
    assignment_id: UUID
    mode: Literal["TEAM", "CLASS"]
    criteria_text: str = Field("", max_length=5000)
    criteria_file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    due_at: datetime
class CampaignTargetIn(BaseModel):
    class_id: UUID; assignment_id: UUID
class CampaignBulkIn(CampaignFields):
    targets: list[CampaignTargetIn] = Field(min_length=1)
class CampaignUpdateIn(CampaignFields):
    version: int
class ReviewIn(BaseModel):
    score: float | None = Field(None, ge=0, le=100)
    comment: str = Field(max_length=2000)
    reviewee_id: UUID | None = None
    scores: dict[str, float] | None = None
class GradeIn(BaseModel):
    assignment_id: UUID; subject_user_id: UUID | None = None; subject_team_id: UUID | None = None; score: float = Field(ge=0, le=100); comment: str = Field("", max_length=2000); publish: bool = False; reason: str = Field("", max_length=500)
class AssignmentUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=100); description: str | None = Field(None, min_length=1, max_length=5000); starts_at: datetime | None = None; due_at: datetime | None = None; allow_late: bool | None = None; submitter_type: Literal["TEAM", "INDIVIDUAL"] | None = None; version: int
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
    max_team_members: int | None = Field(None, ge=2, le=20)
    topic_public: bool | None = None
    invite_requires_approval: bool | None = None
    status: Literal["ACTIVE", "ARCHIVED"] | None = None
class MemberCreateIn(BaseModel):
    student_no: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
class MemberUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@app.get("/health/live")
def live(): return {"status": "ok", "service": "coursework-api"}


@app.get("/health/ready")
def ready(response: Response):
    try:
        with psycopg.connect(settings.database_url.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=2) as conn: conn.execute("SELECT 1")
        settings.file_root.mkdir(parents=True, exist_ok=True)
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
    user.password_hash = hash_password(data.new_password); audit(db, user, "PASSWORD_CHANGED", "user", str(user.id)); db.commit(); return Response(status_code=204)


@app.get("/api/v1/classes")
def classes(user: CurrentUser, db: Db):
    q = select(TeachingClass).where(TeachingClass.teacher_id == user.id) if user.role == "TEACHER" else select(TeachingClass).join(ClassMember).where(ClassMember.user_id == user.id, ClassMember.status == "ACTIVE")
    courses = db.scalars(q.order_by(TeachingClass.created_at.desc())).all()
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
    teacher(user); x = TeachingClass(teacher_id=user.id, semester=data.semester.strip(), name=data.name.strip(), invite_code=secrets.token_hex(4).upper(), max_team_members=data.max_team_members, team_deadline=data.team_deadline, topic_public=data.topic_public, invite_requires_approval=data.invite_requires_approval)
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
    active = db.scalar(select(func.count()).select_from(Assignment).where(Assignment.class_id == cid, Assignment.status == "PUBLISHED", Assignment.due_at >= now())) or 0
    latest_assignment = db.scalar(select(Assignment).where(Assignment.class_id == cid, Assignment.status == "PUBLISHED", Assignment.due_at >= now()).order_by(Assignment.created_at.desc()).limit(1))
    assignment_expected = (members if latest_assignment.submitter_type == "INDIVIDUAL" else teams) if latest_assignment else 0
    assignment_submitted = db.scalar(select(func.count()).select_from(Submission).where(Submission.assignment_id == latest_assignment.id, Submission.status == "SUBMITTED")) if latest_assignment else 0

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
            "active_assignments": active,
            "submission_rate": round((assignment_submitted or 0) * 100 / assignment_expected, 1) if assignment_expected else 0,
            "submission_assignment_title": latest_assignment.title if latest_assignment else None,
            "submission_assignment_due_at": latest_assignment.due_at if latest_assignment else None,
            "peer_review_rate": round(review_completed * 100 / review_expected, 1) if review_expected else 0,
            "peer_review_assignment_title": latest_campaign_assignment.title if latest_campaign_assignment else None,
            "peer_review_due_at": latest_campaign.due_at if latest_campaign else None,
        },
    }


def parse_roster(content: bytes, filename: str):
    if filename.lower().endswith(".csv"):
        return [(str(r.get("学号", "")).strip(), str(r.get("姓名", "")).strip()) for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig")))]
    if filename.lower().endswith(".xlsx"):
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for sheet in workbook.worksheets:
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
    student.password_hash = hash_password(student.login_name); audit(db, user, "PASSWORD_RESET", "user", str(uid)); db.commit(); return Response(status_code=204)


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
    x = Team(class_id=course.id, leader_id=user.id, name=data.name.strip(), normalized_name="".join(data.name.casefold().split()), open_recruitment=data.open_recruitment, max_members=course.max_team_members); db.add(x)
    try:
        db.flush(); db.add(TeamMember(team_id=x.id, class_id=course.id, user_id=user.id, role="LEADER")); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == course.id, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); audit(db, user, "TEAM_CREATED", "team", str(x.id)); db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "TEAM_NAME_EXISTS", "小组名称已被使用")
    return team_json(db, x, user)


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


@app.get("/api/v1/team-requests")
def requests(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id); q = select(TeamRequest, Team, User).join(Team, Team.id == TeamRequest.team_id).join(User, User.id == TeamRequest.applicant_id).where(TeamRequest.class_id == class_id)
    if user.role == "STUDENT": q = q.where(or_(TeamRequest.applicant_id == user.id, Team.leader_id == user.id))
    rows = db.execute(q.order_by(TeamRequest.created_at.desc())).all(); return {"items": [{"id": str(r.id), "team_id": str(t.id), "team_name": t.name, "applicant_id": str(p.id), "applicant_name": p.display_name, "kind": r.kind, "status": r.status, "is_incoming": t.leader_id == user.id} for r, t, p in rows]}


@app.post("/api/v1/team-requests/{rid}/decision")
def request_decision(rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    req = db.scalar(select(TeamRequest).where(TeamRequest.id == rid).with_for_update()); x = db.scalar(select(Team).where(Team.id == req.team_id).with_for_update()) if req else None
    if not req or req.status != "PENDING": raise ApiError(409, "REQUEST_NOT_PENDING", "申请已处理")
    if not x or x.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可处理申请")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    if decision == "APPROVED":
        if membership(db, req.class_id, req.applicant_id): raise ApiError(409, "ALREADY_IN_TEAM", "申请人已加入其他小组")
        count = db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == x.id, TeamMember.status == "ACTIVE")) or 0
        if count >= x.max_members: raise ApiError(409, "TEAM_FULL", "小组人数已满")
        db.add(TeamMember(team_id=x.id, class_id=req.class_id, user_id=req.applicant_id)); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == req.class_id, TeamRequest.applicant_id == req.applicant_id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); req.status = "APPROVED"; notify(db, req.applicant_id, "TEAM_JOINED", f"已加入小组「{x.name}」")
    else: req.status, req.resolved_at = "REJECTED", now(); notify(db, req.applicant_id, "TEAM_REJECTED", f"加入「{x.name}」的申请未通过")
    audit(db, user, "TEAM_REQUEST_DECIDED", "team_request", str(req.id), {"decision": decision}); db.commit(); return {"id": str(req.id), "status": req.status}


@app.delete("/api/v1/team-requests/{rid}", status_code=204)
def cancel_request(rid: UUID, user: CsrfUser, db: Db):
    req = db.get(TeamRequest, rid)
    can_cancel = req and (req.applicant_id == user.id or (req.kind == "INVITATION" and req.inviter_id == user.id))
    if not can_cancel or req.status != "PENDING": raise ApiError(409, "REQUEST_NOT_CANCELLABLE", "申请或邀请无法取消")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    req.status, req.resolved_at = "CANCELLED", now(); db.commit(); return Response(status_code=204)


@app.post("/api/v1/teams/{tid}/topic")
def topic(tid: UUID, data: TopicIn, user: CsrfUser, db: Db):
    x = db.get(Team, tid)
    if not x or x.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可提交选题")
    require_writable_class(db, user, x.class_id)
    norm = "".join(data.name.casefold().split()); item = db.scalar(select(Topic).where(Topic.team_id == tid))
    if item: item.name, item.normalized_name, item.description, item.review_status, item.version = data.name.strip(), norm, data.description, "PENDING", item.version + 1
    else: item = Topic(class_id=x.class_id, team_id=tid, name=data.name.strip(), normalized_name=norm, description=data.description); db.add(item)
    try: db.flush(); audit(db, user, "TOPIC_SUBMITTED", "team", str(tid)); db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "TOPIC_DUPLICATE", "该选题已被使用，请重新填写")
    return {"id": str(item.id), "name": item.name, "status": item.review_status}


def assignment_json(x: Assignment): return {"id": str(x.id), "class_id": str(x.class_id), "title": x.title, "description": render_description(x.description), "submitter_type": x.submitter_type, "starts_at": x.starts_at, "due_at": x.due_at, "allow_late": x.allow_late, "auto_review_enabled": x.auto_review_enabled, "auto_review_mode": x.auto_review_mode, "auto_review_criteria_text": x.auto_review_criteria_text or "", "auto_review_due_at": x.auto_review_due_at, "auto_review_status": x.auto_review_status, "auto_review_error": x.auto_review_error, "status": x.status, "version": x.version}


def file_json(file: FileObject, owner_name: str | None = None, submitted: bool = False) -> dict:
    suffix = Path(file.original_name).suffix.lower()
    previewable = suffix in {".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    return {"id": str(file.id), "name": file.original_name, "size": file.size_bytes, "preview_status": file.preview_status, "preview_error": file.preview_error, "previewable": previewable, "download_only": not previewable, "purpose": file.purpose, "owner_name": owner_name, "created_at": file.created_at, "submitted": submitted}


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
    if user.role == "STUDENT": require_team(db, class_id, user)
    q = select(Assignment).where(Assignment.class_id == class_id)
    if user.role == "STUDENT": q = q.where(Assignment.status.in_(["PUBLISHED", "CLOSED"]))
    items = db.scalars(q.order_by(Assignment.created_at.desc())).all()
    result = []
    for item in items:
        payload = assignment_json(item)
        if user.role == "STUDENT":
            submission, _ = own_submission(db, item, user)
            payload["submission_status"] = submission.status if submission else "NOT_SUBMITTED"
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
    for key in ("title", "description", "starts_at", "due_at", "allow_late", "submitter_type"):
        value = getattr(data, key)
        if value is not None:
            if key == "description": value = clean_html(value)
            setattr(assignment, key, value.strip() if isinstance(value, str) else value)
    assignment.version += 1; audit(db, user, "ASSIGNMENT_UPDATED", "assignment", str(aid)); db.commit(); return assignment_json(assignment)


@app.post("/api/v1/assignments/{aid}/publish")
def publish_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status == "PUBLISHED": return assignment_json(assignment)
    if assignment.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "已提前截止的作业请先撤回发布后再重新发布")
    if assignment.auto_review_enabled:
        criteria_exists = bool(db.scalar(select(FileObject.id).where(FileObject.assignment_id == aid, FileObject.purpose == "REVIEW_CRITERIA").limit(1)))
        if not (assignment.auto_review_criteria_text or "").strip() and not criteria_exists: raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "自动互评标准文字和附件至少提供一种")
        if assignment.submitter_type != "INDIVIDUAL" or not assignment.auto_review_mode or not assignment.auto_review_due_at or assignment.auto_review_due_at <= assignment.due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_INVALID", "自动互评配置不完整")
    assignment.status = "PUBLISHED"; assignment.version += 1
    for member in db.scalars(select(ClassMember).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE")): notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"新作业：{assignment.title}")
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
    paths = [settings.file_root / item.storage_path for item in db.scalars(select(FileObject).where(FileObject.assignment_id == aid)).all()]
    title = assignment.title
    audit(db, user, "ASSIGNMENT_DELETED", "assignment", str(aid), {"title": title})
    db.delete(assignment)
    db.commit()
    for path in paths:
        if path.is_file(): path.unlink()
    export_path = settings.file_root / "exports" / f"{aid}.zip"
    if export_path.is_file(): export_path.unlink()
    return Response(status_code=204)


def own_submission(db: Session, a: Assignment, user: User):
    if a.submitter_type == "INDIVIDUAL": return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == user.id)), None
    _, x = require_team(db, a.class_id, user); return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_team_id == x.id)), x


@app.post("/api/v1/assignments/{aid}/files", status_code=201)
async def upload(aid: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...), purpose: Literal["ATTACHMENT", "REVIEW_CRITERIA"] | None = Query(None)):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, a.class_id)
    team = None
    if user.role == "STUDENT":
        if a.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续上传附件")
        if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
        if a.starts_at and a.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
        _, team = require_team(db, a.class_id, user)
    suffix = Path(file.filename or "file").suffix.lower()
    supported = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".md", ".docx", ".pptx", ".xlsx", ".zip", ".rar", ".7z"}
    if suffix not in supported: raise ApiError(422, "FILE_TYPE_INVALID", "仅支持 Markdown、PDF、常见图片、Office 文档和 ZIP/RAR/7Z 压缩包")
    expected_mimes = {
        ".md": {"text/markdown", "text/plain", "application/octet-stream"}, ".pdf": {"application/pdf"},
        ".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"}, ".gif": {"image/gif"}, ".webp": {"image/webp"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        ".zip": {"application/zip", "application/x-zip-compressed"}, ".rar": {"application/vnd.rar", "application/x-rar-compressed"}, ".7z": {"application/x-7z-compressed"},
    }
    if suffix in expected_mimes and file.content_type and file.content_type not in expected_mimes[suffix]:
        raise ApiError(422, "FILE_MIME_INVALID", "文件 MIME 类型与扩展名不匹配")
    fid = uuid4(); relative = f"{aid}/{fid.hex}{suffix}"; target = settings.file_root / relative; target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.uploading")
    size = 0
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空且不得超过 100 MB")
                output.write(chunk)
        if not size: raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空")
        os.replace(temporary, target)
    except Exception:
        if temporary.exists(): temporary.unlink()
        raise
    finally:
        await file.close()
    selected_purpose = (purpose or "ATTACHMENT") if user.role == "TEACHER" else "SUBMISSION"
    team_id = team.id if team and a.submitter_type == "TEAM" else None
    preview_status = "READY" if suffix in {".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"} else "NOT_AVAILABLE"
    x = FileObject(id=fid, owner_id=user.id, assignment_id=aid, team_id=team_id, purpose=selected_purpose, storage_path=relative, original_name=Path(file.filename or "file").name, size_bytes=size, detected_mime=file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream", preview_status=preview_status)
    db.add(x)
    db.commit()
    return file_json(x, user.display_name)


@app.get("/api/v1/assignments/{aid}/files")
def assignment_files(aid: UUID, user: CurrentUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    team = require_team(db, assignment.class_id, user)[1] if user.role == "STUDENT" else None
    materials = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT").order_by(FileObject.created_at)).all()
    criteria = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "REVIEW_CRITERIA").order_by(FileObject.created_at)).all()
    drafts = []
    if user.role == "STUDENT":
        q = select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active.is_(True))
        q = q.where(FileObject.owner_id == user.id) if assignment.submitter_type == "INDIVIDUAL" else q.where(FileObject.team_id == team.id)
        drafts = db.scalars(q.order_by(FileObject.created_at)).all()
    def item(file: FileObject):
        linked = bool(db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == file.id).limit(1)))
        owner = db.get(User, file.owner_id)
        return file_json(file, owner.display_name, linked)
    return {"attachments": [item(x) for x in materials], "review_criteria": [item(x) for x in criteria], "drafts": [item(x) for x in drafts]}


@app.delete("/api/v1/files/{fid}", status_code=204)
def delete_file(fid: UUID, user: CsrfUser, db: Db):
    file = db.get(FileObject, fid); assignment = db.get(Assignment, file.assignment_id) if file else None
    if not file or not assignment: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, assignment.class_id)
    if file.owner_id != user.id: raise ApiError(403, "FILE_FORBIDDEN", "只能删除自己上传的文件")
    if file.purpose in {"ATTACHMENT", "REVIEW_CRITERIA"} and assignment.status != "DRAFT": raise ApiError(409, "PUBLISHED_FILE_LOCKED", "已发布作业的教师附件不能删除")
    if db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == fid).limit(1)):
        file.active = False
        db.commit()
        return Response(status_code=204)
    path = settings.file_root / file.storage_path; db.delete(file); db.commit()
    if path.is_file(): path.unlink()
    return Response(status_code=204)


@app.get("/api/v1/assignments/{aid}/submission")
def submission(aid: UUID, user: CurrentUser, db: Db):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    s, _ = own_submission(db, a, user)
    latest = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s else None
    files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == latest.id)).all() if latest else []
    return {"status": s.status if s else "EMPTY", "submitted_at": latest.submitted_at if latest else None, "is_late": latest.is_late if latest else False, "files": [file_json(file) for file in files]}


@app.post("/api/v1/assignments/{aid}/submission", status_code=201)
def submit(aid: UUID, user: CsrfUser, db: Db, idempotency_key: Annotated[str | None, Header()] = None):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    if a.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续提交")
    if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    require_writable_class(db, user, a.class_id)
    if a.starts_at and a.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
    s, team = own_submission(db, a, user)
    if team and team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "小组作业仅组长可正式提交")
    if a.due_at < now() and not a.allow_late: raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止且不允许迟交")
    file_scope = FileObject.owner_id == user.id if not team else FileObject.team_id == team.id
    files = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active.is_(True), file_scope).order_by(FileObject.created_at)).all()
    if not files: raise ApiError(422, "SUBMISSION_FILES_REQUIRED", "请先上传作业附件")
    if not s: s = Submission(assignment_id=aid, owner_user_id=user.id if not team else None, owner_team_id=team.id if team else None); db.add(s); db.flush()
    current = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s.current_version_no else None
    if idempotency_key and current and current.idempotency_key == idempotency_key:
        return {"id": str(s.id), "submitted_at": current.submitted_at, "is_late": current.is_late}
    snapshot = {}
    if team:
        rows = db.execute(select(TeamMember, User).join(User).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE").order_by(User.login_name)).all()
        snapshot = {"members": [{"id": str(person.id), "student_no": person.login_name, "name": person.display_name, "role": member.role} for member, person in rows]}
    submitted_at = now()
    if current:
        db.execute(delete(VersionFile).where(VersionFile.version_id == current.id))
        current.submitted_by, current.submitted_at = user.id, submitted_at
        current.member_snapshot, current.is_late, current.idempotency_key = snapshot, a.due_at < submitted_at, idempotency_key
        v = current
    else:
        s.current_version_no = 1
        v = SubmissionVersion(submission_id=s.id, version_no=1, submitted_by=user.id, submitted_at=submitted_at, member_snapshot=snapshot, is_late=a.due_at < submitted_at, idempotency_key=idempotency_key)
        db.add(v); db.flush()
    old_versions = db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.id != v.id)).all()
    for old in old_versions:
        frozen = db.scalar(select(ReviewAssignment.id).where(ReviewAssignment.submission_version_id == old.id).limit(1)) or db.scalar(select(PeerReview.id).where(PeerReview.submission_version_id == old.id).limit(1))
        if not frozen: db.delete(old)
    s.status = "SUBMITTED"
    for f in files: db.add(VersionFile(version_id=v.id, file_id=f.id))
    db.flush()
    stale_paths = []
    inactive = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active.is_(False), file_scope)).all()
    for file in inactive:
        if not db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == file.id).limit(1)):
            stale_paths.append(settings.file_root / file.storage_path)
            db.delete(file)
    audit(db, user, "SUBMISSION_CREATED", "submission", str(s.id)); db.commit()
    for path in stale_paths:
        if path.is_file(): path.unlink()
    return {"id": str(s.id), "submitted_at": v.submitted_at, "is_late": v.is_late}


@app.get("/api/v1/files/{fid}")
def download(fid: UUID, user: CurrentUser, db: Db):
    f = db.get(FileObject, fid); a = db.get(Assignment, f.assignment_id) if f else None
    if not f or not a: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_class(db, user, a.class_id); allowed = user.role == "TEACHER" or f.owner_id == user.id
    if user.role == "STUDENT":
        own_membership = membership(db, a.class_id, user.id)
        mine = own_membership[1] if own_membership else None
        if f.purpose in {"ATTACHMENT", "REVIEW_CRITERIA"}: allowed = True
        elif f.team_id: allowed = bool(mine and f.team_id == mine.id)
        elif not allowed:
            frozen = db.scalar(select(ReviewAssignment.id).join(ReviewCampaign, ReviewCampaign.id == ReviewAssignment.campaign_id).join(VersionFile, VersionFile.version_id == ReviewAssignment.submission_version_id).where(ReviewCampaign.assignment_id == a.id, ReviewAssignment.reviewer_id == user.id, VersionFile.file_id == f.id, ReviewAssignment.status.in_(["PENDING", "COMPLETED"])).limit(1))
            if frozen:
                allowed = True
            else:
                owner = membership(db, a.class_id, f.owner_id)
                linked = db.execute(select(SubmissionVersion, Submission).join(Submission, Submission.id == SubmissionVersion.submission_id).join(VersionFile, VersionFile.version_id == SubmissionVersion.id).where(VersionFile.file_id == f.id, Submission.status == "SUBMITTED", Submission.current_version_no == SubmissionVersion.version_no)).first()
                legacy = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == a.id, ReviewCampaign.status == "ACTIVE", ReviewCampaign.assignment_snapshot_at.is_(None)))
                allowed = bool(owner and mine and owner[1].id == mine.id and linked and legacy)
    if not allowed: raise ApiError(403, "FILE_FORBIDDEN", "无权访问该文件")
    path = settings.file_root / f.storage_path
    if not path.is_file(): raise ApiError(404, "FILE_MISSING", "文件存储不可用")
    return FileResponse(path, media_type=f.detected_mime, filename=f.original_name)


@app.post("/api/v1/review-campaigns", status_code=201)
def create_campaign(data: AllocatedCampaignIn | CampaignIn, user: CsrfUser, db: Db):
    if isinstance(data, CampaignIn):
        assignment = db.get(Assignment, data.assignment_id)
        if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
        courses = writable_teacher_classes(db, user, [assignment.class_id])
        items = create_campaigns_for_targets(data, [CampaignTargetIn(class_id=courses[0].id, assignment_id=assignment.id)], user, db)
        try: db.commit()
        except IntegrityError: db.rollback(); raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
        item = items[0]; return {"id": str(item.id), "assignment_id": str(item.assignment_id), "status": item.status}
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
    campaign = ReviewCampaign(assignment_id=assignment.id, class_id=assignment.class_id, mode=data.mode, criteria_text=data.criteria_text.strip(), assignment_snapshot_at=snapshot_at, rubric=[{"key": "score", "label": "总分", "weight": 100}], comment_min_length=1, due_at=data.due_at, publish_at=snapshot_at, require_all=False, allow_update=False)
    db.add(campaign); db.flush()
    warnings = []
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
                allocations.append(ReviewAssignment(campaign_id=campaign.id, reviewer_id=person.id, status="SKIPPED", skip_reason=reason))
            continue
        for index, (reviewer, _) in enumerate(rows):
            reviewee, version = rows[(index + 1) % len(rows)]
            allocations.append(ReviewAssignment(campaign_id=campaign.id, reviewer_id=reviewer.id, reviewee_id=reviewee.id, submission_version_id=version.id))
            notify(db, reviewer.id, "REVIEW_ASSIGNED", f"新的互评任务：{assignment.title}")
    db.add_all(allocations)
    audit(db, user, "REVIEW_CAMPAIGN_CREATED", "review_campaign", str(campaign.id), {"mode": data.mode, "allocated": sum(x.status == "PENDING" for x in allocations), "skipped": sum(x.status == "SKIPPED" for x in allocations)})
    try: db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
    return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "status": campaign.status, "mode": campaign.mode, "assignment_snapshot_at": campaign.assignment_snapshot_at, "allocated": sum(x.status == "PENDING" for x in allocations), "skipped": sum(x.status == "SKIPPED" for x in allocations), "warnings": warnings}


def create_campaigns_for_targets(data: CampaignFields, targets: list[CampaignTargetIn], user: User, db: Session) -> list[ReviewCampaign]:
    if abs(sum(float(x.get("weight", 0)) for x in data.rubric) - 100) > .01 or any(not x.get("key") or not x.get("label") for x in data.rubric): raise ApiError(422, "RUBRIC_INVALID", "评价维度权重合计必须为 100")
    class_ids = [x.class_id for x in targets]
    writable_teacher_classes(db, user, class_ids)
    assignment_ids = [x.assignment_id for x in targets]
    if len(set(assignment_ids)) != len(assignment_ids): raise ApiError(422, "DUPLICATE_ASSIGNMENT", "互评作业不能重复选择")
    assignments = db.scalars(select(Assignment).where(Assignment.id.in_(assignment_ids)).with_for_update()).all()
    by_id = {x.id: x for x in assignments}
    if len(by_id) != len(assignment_ids): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "部分作业不存在")
    for target in targets:
        assignment = by_id[target.assignment_id]
        if assignment.class_id != target.class_id: raise ApiError(422, "ASSIGNMENT_CLASS_MISMATCH", "所选作业不属于对应教学班")
        if assignment.submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "作品互评只能关联个人作业")
    existing = db.scalars(select(ReviewCampaign.assignment_id).where(ReviewCampaign.assignment_id.in_(assignment_ids))).all()
    if existing: raise ApiError(409, "CAMPAIGN_EXISTS", "部分作业已创建互评活动", {"assignment_ids": [str(x) for x in existing]})
    created = [ReviewCampaign(assignment_id=target.assignment_id, class_id=target.class_id, rubric=data.rubric, comment_min_length=data.comment_min_length, due_at=data.due_at, publish_at=data.publish_at, require_all=data.require_all, allow_update=data.allow_update) for target in targets]
    db.add_all(created)
    try: db.flush()
    except IntegrityError: db.rollback(); raise ApiError(409, "CAMPAIGN_EXISTS", "部分作业已创建互评活动")
    for item in created: audit(db, user, "REVIEW_CAMPAIGN_CREATED", "review_campaign", str(item.id), {"class_id": str(item.class_id), "assignment_id": str(item.assignment_id)})
    return created


@app.post("/api/v1/review-campaigns/bulk", status_code=201)
def create_campaigns_bulk(data: CampaignBulkIn, user: CsrfUser, db: Db):
    items = create_campaigns_for_targets(data, data.targets, user, db)
    db.commit()
    return {"items": [{"id": str(x.id), "class_id": str(x.class_id), "assignment_id": str(x.assignment_id), "status": x.status} for x in items], "total": len(items)}


@app.get("/api/v1/review-campaigns")
def campaigns(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    query = select(ReviewCampaign, Assignment).join(Assignment).where(ReviewCampaign.class_id == class_id)
    if user.role == "STUDENT": query = query.where(or_(ReviewCampaign.publish_at.is_(None), ReviewCampaign.publish_at <= now()))
    rows = db.execute(query.order_by(ReviewCampaign.due_at.desc())).all()
    items = []
    for c, a in rows:
        payload = {"id": str(c.id), "assignment_id": str(a.id), "assignment_title": a.title, "mode": c.mode, "criteria_text": c.criteria_text, "assignment_snapshot_at": c.assignment_snapshot_at, "rubric": c.rubric, "comment_min_length": c.comment_min_length, "due_at": c.due_at, "publish_at": c.publish_at, "require_all": c.require_all, "allow_update": c.allow_update, "status": c.status, "version": c.version, "completed": db.scalar(select(func.count()).select_from(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.status == "VALID")) or 0}
        if user.role == "STUDENT":
            allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == c.id, ReviewAssignment.reviewer_id == user.id))
            payload["pending_count"] = 1 if allocation and allocation.status == "PENDING" else 0
            payload["allocation_status"] = allocation.status if allocation else None
            payload["skip_reason"] = allocation.skip_reason if allocation else None
        items.append(payload)
    return {"items": items, "total": len(items)}


@app.get("/api/v1/review-campaigns/{cid}/candidates")
def candidates(cid: UUID, user: CurrentUser, db: Db):
    c = db.get(ReviewCampaign, cid)
    if not c: raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    if c.status != "ACTIVE" or (c.publish_at and c.publish_at > now()) or c.due_at < now(): raise ApiError(409, "CAMPAIGN_CLOSED", "互评活动未开放或已截止")
    _, team = require_team(db, c.class_id, user); a = db.get(Assignment, c.assignment_id); people = db.scalars(select(User).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE", User.id != user.id)).all(); items = []
    for person in people:
        s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == person.id, Submission.status == "SUBMITTED")); v = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s else None
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == v.id)).all() if v else []; reviewed = db.scalar(select(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.reviewer_id == user.id, PeerReview.reviewee_id == person.id, PeerReview.status == "VALID"))
        items.append({"user_id": str(person.id), "name": person.display_name, "student_no": person.login_name, "submitted": bool(v), "submitted_at": v.submitted_at if v else None, "files": [{"id": str(f.id), "name": f.original_name, "size": f.size_bytes} for f in files], "reviewed": bool(reviewed), "review": None if not reviewed else {"id": str(reviewed.id), "scores": reviewed.scores, "comment": reviewed.comment, "total_score": reviewed.total_score}})
    return {"items": items, "campaign": {"id": str(c.id), "assignment_title": a.title, "rubric": c.rubric, "comment_min_length": c.comment_min_length, "due_at": c.due_at, "allow_update": c.allow_update}}


@app.get("/api/v1/review-campaigns/{cid}/assignment")
def allocated_assignment(cid: UUID, user: CurrentUser, db: Db):
    campaign = db.get(ReviewCampaign, cid)
    if not campaign: raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_class(db, user, campaign.class_id)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生查看自己的互评任务")
    allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == cid, ReviewAssignment.reviewer_id == user.id))
    if not allocation: raise ApiError(404, "REVIEW_ASSIGNMENT_NOT_FOUND", "当前活动没有分配给你的任务")
    assignment = db.get(Assignment, campaign.assignment_id)
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
    require_writable_class(db, user, c.class_id)
    if c.assignment_snapshot_at is not None:
        allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == c.id, ReviewAssignment.reviewer_id == user.id).with_for_update())
        if not allocation: raise ApiError(403, "REVIEW_NOT_ASSIGNED", "当前活动没有分配给你的互评任务")
        if allocation.status == "SKIPPED": raise ApiError(409, "REVIEW_ASSIGNMENT_SKIPPED", allocation.skip_reason or "该互评任务已跳过")
        if allocation.status != "PENDING": raise ApiError(409, "REVIEW_DUPLICATE", "该互评任务已提交")
        if data.score is None: raise ApiError(422, "SCORE_REQUIRED", "请填写 0 至 100 的总分")
        comment = data.comment.strip()
        if not comment: raise ApiError(422, "COMMENT_REQUIRED", "评语不能为空")
        existing = db.scalar(select(PeerReview).where(PeerReview.allocation_id == allocation.id))
        scores = {"score": data.score}
        if existing:
            existing.reviewer_id, existing.reviewee_id, existing.submission_version_id = allocation.reviewer_id, allocation.reviewee_id, allocation.submission_version_id
            existing.scores, existing.total_score, existing.comment, existing.status, existing.invalid_reason = scores, data.score, comment, "VALID", None
            item = existing
        else:
            item = PeerReview(allocation_id=allocation.id, campaign_id=c.id, reviewer_id=allocation.reviewer_id, reviewee_id=allocation.reviewee_id, submission_version_id=allocation.submission_version_id, scores=scores, total_score=data.score, comment=comment)
            db.add(item)
        allocation.status = "COMPLETED"
        notify(db, allocation.reviewee_id, "REVIEW_RECEIVED", f"收到来自 {user.display_name} 的作品评价")
        db.flush(); audit(db, user, "PEER_REVIEW_SUBMITTED", "peer_review", str(item.id), {"allocation_id": str(allocation.id)}); db.commit()
        return {"id": str(item.id), "allocation_id": str(allocation.id), "total_score": data.score, "status": item.status}
    if data.reviewee_id is None or data.scores is None: raise ApiError(422, "LEGACY_REVIEW_INVALID", "旧互评活动需要评价对象和评分维度")
    if data.reviewee_id == user.id: raise ApiError(422, "SELF_REVIEW_FORBIDDEN", "不能评价自己")
    _, mine = require_team(db, c.class_id, user); other = membership(db, c.class_id, data.reviewee_id)
    if not other or other[1].id != mine.id: raise ApiError(403, "CROSS_TEAM_REVIEW_FORBIDDEN", "只能评价本组其他成员")
    a = db.get(Assignment, c.assignment_id); s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == data.reviewee_id, Submission.status == "SUBMITTED")); v = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s else None
    if not v: raise ApiError(409, "SUBMISSION_REQUIRED", "该成员尚未正式提交作品")
    if len(data.comment.strip()) < c.comment_min_length: raise ApiError(422, "COMMENT_TOO_SHORT", f"评语至少需要 {c.comment_min_length} 个字")
    keys = {str(x["key"]) for x in c.rubric}
    if set(data.scores) != keys or any(n < 0 or n > 100 for n in data.scores.values()): raise ApiError(422, "SCORES_INVALID", "评分维度不完整或超出 0 至 100")
    total = round(sum(data.scores[str(x["key"])] * float(x["weight"]) / 100 for x in c.rubric), 2); x = db.scalar(select(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.reviewer_id == user.id, PeerReview.reviewee_id == data.reviewee_id, PeerReview.status == "VALID"))
    if x and not c.allow_update: raise ApiError(409, "REVIEW_DUPLICATE", "已提交对该成员的评价")
    if x: x.scores, x.total_score, x.comment, x.submission_version_id = data.scores, total, data.comment.strip(), v.id
    else: x = PeerReview(campaign_id=c.id, reviewer_id=user.id, reviewee_id=data.reviewee_id, submission_version_id=v.id, scores=data.scores, total_score=total, comment=data.comment.strip()); db.add(x)
    notify(db, data.reviewee_id, "REVIEW_RECEIVED", f"收到来自 {user.display_name} 的作品评价"); db.flush(); audit(db, user, "PEER_REVIEW_SUBMITTED", "peer_review", str(x.id)); db.commit(); return {"id": str(x.id), "total_score": total, "status": x.status}


@app.get("/api/v1/peer-reviews/received")
def received(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id); reviewer = aliased(User)
    result_visible = or_(and_(ReviewCampaign.assignment_snapshot_at.is_not(None), ReviewCampaign.due_at <= now()), and_(ReviewCampaign.assignment_snapshot_at.is_(None), or_(ReviewCampaign.publish_at.is_(None), ReviewCampaign.publish_at <= now())))
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
    x.status, x.invalid_reason = "INVALID", data.reason
    if x.allocation_id:
        allocation = db.get(ReviewAssignment, x.allocation_id)
        if allocation: allocation.status = "PENDING"
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
    if user.role == "STUDENT": require_team(db, class_id, user)
    rows = db.execute(select(Grade, Assignment).join(Assignment).where(Assignment.class_id == class_id).order_by(Grade.updated_at.desc())).all(); items = []
    team = membership(db, class_id, user.id)[1] if user.role == "STUDENT" else None
    for g, a in rows:
        if user.role == "STUDENT" and (g.status != "PUBLISHED" or (g.subject_user_id != user.id and g.subject_team_id != team.id)): continue
        subject = db.get(User, g.subject_user_id) if g.subject_user_id else db.get(Team, g.subject_team_id)
        items.append({"id": str(g.id), "assignment_id": str(a.id), "assignment_title": a.title, "subject_id": str(subject.id), "subject_type": "USER" if isinstance(subject, User) else "TEAM", "subject_name": subject.display_name if isinstance(subject, User) else subject.name, "score": g.score, "comment": g.comment, "status": g.status, "version": g.version})
    return {"items": items, "total": len(items)}


@app.post("/api/v1/grades", status_code=201)
def save_grade(data: GradeIn, user: CsrfUser, db: Db):
    teacher(user); a = db.get(Assignment, data.assignment_id)
    if not a or not user_class(db, user, a.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, a.class_id)
    if bool(data.subject_user_id) == bool(data.subject_team_id): raise ApiError(422, "GRADE_SUBJECT_INVALID", "评分对象必须是一个学生或一个小组")
    if a.submitter_type == "INDIVIDUAL":
        valid = data.subject_user_id and db.scalar(select(ClassMember.id).where(ClassMember.class_id == a.class_id, ClassMember.user_id == data.subject_user_id, ClassMember.status == "ACTIVE"))
    else:
        valid = data.subject_team_id and db.scalar(select(Team.id).where(Team.id == data.subject_team_id, Team.class_id == a.class_id, Team.status == "ACTIVE"))
    if not valid: raise ApiError(422, "GRADE_SUBJECT_INVALID", "评分对象与作业提交类型不匹配")
    q = select(Grade).where(Grade.assignment_id == a.id); q = q.where(Grade.subject_user_id == data.subject_user_id) if data.subject_user_id else q.where(Grade.subject_team_id == data.subject_team_id); g = db.scalar(q)
    if g:
        if g.status == "PUBLISHED" and (g.score != data.score or g.comment != data.comment) and len(data.reason.strip()) < 2: raise ApiError(422, "GRADE_CHANGE_REASON_REQUIRED", "修改已发布成绩时必须填写原因")
        db.add(GradeRevision(grade_id=g.id, changed_by=user.id, score=g.score, comment=g.comment, status=g.status, reason=data.reason.strip()))
        g.score, g.comment, g.status, g.version = data.score, data.comment, "PUBLISHED" if data.publish else "DRAFT", g.version + 1
    else: g = Grade(assignment_id=a.id, subject_user_id=data.subject_user_id, subject_team_id=data.subject_team_id, score=data.score, comment=data.comment, status="PUBLISHED" if data.publish else "DRAFT"); db.add(g)
    db.flush();
    recipients = [data.subject_user_id] if data.subject_user_id else list(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == data.subject_team_id, TeamMember.status == "ACTIVE")))
    if data.publish:
        for recipient in recipients: notify(db, recipient, "GRADE_PUBLISHED", f"成绩已发布：{a.title}")
    audit(db, user, "GRADE_SAVED", "grade", str(g.id), {"reason": data.reason.strip(), "published": data.publish}); db.commit(); return {"id": str(g.id), "score": g.score, "status": g.status, "version": g.version}


@app.get("/api/v1/grades/{gid}/revisions")
def grade_revisions(gid: UUID, user: CurrentUser, db: Db):
    teacher(user); grade = db.get(Grade, gid); assignment = db.get(Assignment, grade.assignment_id) if grade else None
    if not grade or not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "GRADE_NOT_FOUND", "成绩不存在")
    rows = db.scalars(select(GradeRevision).where(GradeRevision.grade_id == gid).order_by(GradeRevision.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "score": item.score, "comment": item.comment, "status": item.status, "reason": item.reason, "created_at": item.created_at} for item in rows]}


@app.get("/api/v1/notifications")
def notifications(user: CurrentUser, db: Db):
    items = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)).all(); return {"items": [{"id": str(x.id), "title": x.title, "kind": x.kind, "read": bool(x.read_at), "created_at": x.created_at} for x in items], "unread": sum(not x.read_at for x in items)}


@app.post("/api/v1/notifications/read", status_code=204)
def read_notifications(user: CsrfUser, db: Db):
    db.execute(Notification.__table__.update().where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=now())); db.commit(); return Response(status_code=204)


@app.get("/api/v1/audit-logs")
def audit_logs(user: CurrentUser, db: Db, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    teacher(user); total = db.scalar(select(func.count()).select_from(AuditLog)) or 0; rows = db.execute(select(AuditLog, User).outerjoin(User).order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all(); return {"items": [{"id": str(x.id), "actor": p.display_name if p else "系统", "action": x.action, "object_type": x.object_type, "object_id": x.object_id, "changes": x.changes, "created_at": x.created_at} for x, p in rows], "page": page, "page_size": page_size, "total": total}


def export_rows(kind: str, class_id: UUID, user: User, db: Session) -> list[list]:
    rows: list[list] = []
    if kind == "members":
        rows.append(["学号", "姓名", "状态", "小组"])
        for member, person in db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == class_id)):
            team = membership(db, class_id, person.id)
            rows.append([person.login_name, person.display_name, member.status, team[1].name if team else ""])
    elif kind == "teams":
        rows.append(["小组", "组长", "人数", "选题", "状态"])
        for team in db.scalars(select(Team).where(Team.class_id == class_id)):
            item = team_json(db, team, user); rows.append([item["name"], item["leader_name"], item["member_count"], item["topic"]["name"] if item["topic"] else "", item["status"]])
    elif kind == "grades":
        rows.append(["作业", "评分对象", "分数", "状态", "评语"])
        for grade, assignment in db.execute(select(Grade, Assignment).join(Assignment).where(Assignment.class_id == class_id)):
            subject = db.get(User, grade.subject_user_id) if grade.subject_user_id else db.get(Team, grade.subject_team_id)
            rows.append([assignment.title, subject.display_name if isinstance(subject, User) else subject.name, grade.score, grade.status, grade.comment])
    else:
        rows.append(["作业", "评价人", "被评价人", "总分", "状态", "评语"])
        for review, assignment in db.execute(select(PeerReview, Assignment).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment).where(ReviewCampaign.class_id == class_id)):
            rows.append([assignment.title, db.get(User, review.reviewer_id).display_name, db.get(User, review.reviewee_id).display_name, review.total_score, review.status, review.comment])
    return rows


@app.get("/api/v1/exports/{kind}.csv")
def export_csv(kind: Literal["members", "teams", "grades", "reviews"], user: CurrentUser, db: Db, class_id: UUID = Query()):
    teacher(user); require_class(db, user, class_id); out = io.StringIO(); writer = csv.writer(out); writer.writerows(export_rows(kind, class_id, user, db))
    return PlainTextResponse("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@app.get("/api/v1/exports/{kind}.xlsx")
def export_xlsx(kind: Literal["members", "teams", "grades", "reviews"], user: CurrentUser, db: Db, class_id: UUID = Query()):
    teacher(user); require_class(db, user, class_id); workbook = Workbook(); sheet = workbook.active; sheet.title = "导出数据"
    for row in export_rows(kind, class_id, user, db): sheet.append(row)
    target = settings.file_root / "exports" / f"{kind}-{class_id}.xlsx"; target.parent.mkdir(parents=True, exist_ok=True); workbook.save(target)
    return FileResponse(target, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=f"{kind}.xlsx")


@app.patch("/api/v1/classes/{cid}")
def update_class(cid: UUID, data: ClassUpdateIn, user: CsrfUser, db: Db):
    teacher(user)
    course = db.scalar(select(TeachingClass).where(TeachingClass.id == cid, TeachingClass.teacher_id == user.id).with_for_update())
    if not course: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可管理的教学班")
    if course.version != data.version: raise ApiError(409, "CLASS_VERSION_CONFLICT", "教学班已被修改，请刷新后重试", {"current_version": course.version})
    metadata_fields = {"semester", "name", "team_deadline", "max_team_members", "topic_public", "invite_requires_approval"} & data.model_fields_set
    if course.status == "ARCHIVED" and metadata_fields: raise ApiError(409, "CLASS_ARCHIVED", "请先恢复教学班再编辑资料")
    changes = {}
    if data.max_team_members is not None and data.max_team_members != course.max_team_members:
        team_sizes = db.scalars(select(func.count(TeamMember.id)).join(Team, Team.id == TeamMember.team_id).where(Team.class_id == cid, Team.status == "ACTIVE", TeamMember.status == "ACTIVE").group_by(TeamMember.team_id)).all()
        largest_team = max(team_sizes, default=0)
        if data.max_team_members < largest_team: raise ApiError(409, "TEAM_SIZE_LIMIT_TOO_SMALL", "小组人数上限不能低于现有小组人数", {"largest_team_size": largest_team})
        changes["max_team_members"] = {"from": course.max_team_members, "to": data.max_team_members}
        course.max_team_members = data.max_team_members
        for team_item in db.scalars(select(Team).where(Team.class_id == cid, Team.status == "ACTIVE")): team_item.max_members = data.max_team_members
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
    db.delete(course); db.commit(); return Response(status_code=204)


@app.post("/api/v1/teams/{tid}/invitations", status_code=201)
def invite_member(tid: UUID, data: InviteIn, user: CsrfUser, db: Db):
    team = db.get(Team, tid)
    if not team or team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可邀请成员")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
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
        if membership(db, req.class_id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
        count = db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE")) or 0
        if count >= team.max_members: raise ApiError(409, "TEAM_FULL", "小组人数已满")
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
    team = db.get(Team, tid)
    if not team or team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可解散小组")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
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
    rows = db.scalars(select(Submission).where(Submission.assignment_id == aid)).all()
    by_owner = {str(row.owner_user_id or row.owner_team_id): row for row in rows}
    if assignment.submitter_type == "INDIVIDUAL":
        owners = []
        for member, person in db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT").order_by(User.login_name)).all():
            team_row = membership(db, assignment.class_id, person.id)
            owners.append((member.user_id, person.display_name, person.login_name, team_row[1].id if team_row else None, team_row[1].name if team_row else None))
    else:
        owners = [(team.id, team.name, None, team.id, team.name) for team in db.scalars(select(Team).where(Team.class_id == assignment.class_id, Team.status == "ACTIVE").order_by(Team.name)).all()]
    items = []
    for owner_id, owner_name, student_no, team_id, team_name in owners:
        submission = by_owner.get(str(owner_id))
        latest = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == submission.id, SubmissionVersion.version_no == submission.current_version_no)) if submission else None
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == latest.id)).all() if latest and submission.status == "SUBMITTED" else []
        items.append({"id": str(submission.id) if submission else str(owner_id), "owner": owner_name, "student_no": student_no, "team_id": str(team_id) if team_id else None, "team_name": team_name, "status": submission.status if submission else "NOT_SUBMITTED", "submitted_at": latest.submitted_at if latest and submission.status == "SUBMITTED" else None, "is_late": latest.is_late if latest and submission.status == "SUBMITTED" else False, "member_snapshot": latest.member_snapshot if latest else {}, "files": [file_json(file) for file in files]})
    return {"items": items, "total": len(items)}


@app.patch("/api/v1/review-campaigns/{cid}")
def update_campaign(cid: UUID, data: CampaignUpdateIn, user: CsrfUser, db: Db):
    teacher(user); campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == cid).with_for_update())
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_writable_class(db, user, campaign.class_id)
    if campaign.version != data.version: raise ApiError(409, "CAMPAIGN_VERSION_CONFLICT", "互评活动已被修改，请刷新后重试", {"current_version": campaign.version})
    if data.publish_at and data.publish_at >= data.due_at: raise ApiError(422, "CAMPAIGN_TIME_INVALID", "公开时间必须早于截止时间")
    if abs(sum(float(x.get("weight", 0)) for x in data.rubric) - 100) > .01 or any(not x.get("key") or not x.get("label") for x in data.rubric): raise ApiError(422, "RUBRIC_INVALID", "评价维度权重合计必须为 100")
    has_reviews = bool(db.scalar(select(PeerReview.id).where(PeerReview.campaign_id == cid, PeerReview.status == "VALID").limit(1)))
    if has_reviews and data.rubric != campaign.rubric: raise ApiError(409, "CAMPAIGN_RUBRIC_LOCKED", "已有评价后不能修改评分维度或权重")
    campaign.rubric, campaign.comment_min_length = data.rubric, data.comment_min_length
    campaign.due_at, campaign.publish_at = data.due_at, data.publish_at
    campaign.require_all, campaign.allow_update = data.require_all, data.allow_update
    campaign.version += 1
    audit(db, user, "REVIEW_CAMPAIGN_UPDATED", "review_campaign", str(cid)); db.commit()
    return {"id": str(campaign.id), "version": campaign.version, "status": campaign.status}


@app.post("/api/v1/review-campaigns/{cid}/close")
def close_campaign(cid: UUID, user: CsrfUser, db: Db):
    teacher(user); campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == cid).with_for_update())
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_writable_class(db, user, campaign.class_id)
    if campaign.status == "CLOSED":
        return {"id": str(campaign.id), "due_at": campaign.due_at, "status": campaign.status, "version": campaign.version}
    if campaign.status != "ACTIVE": raise ApiError(409, "CAMPAIGN_NOT_ACTIVE", "当前互评活动不能提前截止")
    campaign.status = "CLOSED"
    campaign.due_at = now()
    campaign.version += 1
    audit(db, user, "REVIEW_CAMPAIGN_CLOSED", "review_campaign", str(cid), {"due_at": campaign.due_at.isoformat()})
    db.commit()
    return {"id": str(campaign.id), "due_at": campaign.due_at, "status": campaign.status, "version": campaign.version}


@app.get("/api/v1/files/{fid}/preview")
def preview_file(fid: UUID, user: CurrentUser, db: Db):
    file = db.get(FileObject, fid)
    if not file: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    response = download(fid, user, db)
    path = settings.file_root / file.storage_path
    if path.suffix.lower() == ".md":
        html = markdown.markdown(path.read_text(encoding="utf-8"), extensions=["fenced_code"])
        return HTMLResponse(clean_html(html))
    if path.suffix.lower() in {".docx", ".pptx", ".xlsx"}:
        return response
    # Preview endpoints must render in the browser; the download endpoint keeps
    # the original filename and attachment disposition.
    return FileResponse(path, media_type=file.detected_mime, headers={"Content-Disposition": "inline"})


@app.get("/api/v1/assignments/{aid}/download.zip")
def download_submissions(aid: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    target = settings.file_root / "exports" / f"{aid}.zip"; target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for submission in db.scalars(select(Submission).where(Submission.assignment_id == aid, Submission.status == "SUBMITTED")):
            version = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == submission.id, SubmissionVersion.version_no == submission.current_version_no))
            files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
            owner = db.get(User, submission.owner_user_id) if submission.owner_user_id else db.get(Team, submission.owner_team_id)
            for file in files: archive.write(settings.file_root / file.storage_path, arcname=f"{owner.login_name if isinstance(owner, User) else owner.name}/{file.original_name}")
    audit(db, user, "SUBMISSIONS_EXPORTED", "assignment", str(aid)); db.commit(); return FileResponse(target, media_type="application/zip", filename=f"{assignment.title}.zip")


@app.get("/api/v1/review-campaigns/{cid}/stats")
def campaign_stats(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); campaign = db.get(ReviewCampaign, cid)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    reviews = db.scalars(select(PeerReview).where(PeerReview.campaign_id == cid, PeerReview.status == "VALID")).all()
    if campaign.assignment_snapshot_at is not None:
        allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == cid)).all()
        skipped = [{"reviewer_id": str(x.reviewer_id), "reviewer_name": db.get(User, x.reviewer_id).display_name, "reason": x.skip_reason} for x in allocations if x.status == "SKIPPED"]
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
