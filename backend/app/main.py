from __future__ import annotations

import csv, io, mimetypes, re, secrets
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
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import Assignment, AuditLog, ClassMember, FileObject, Grade, GradeRevision, ImportBatch, LoginSession, Notification, PeerReview, ReviewCampaign, Submission, SubmissionVersion, TeachingClass, Team, TeamMember, TeamRequest, Topic, User, VersionFile
from app.security import hash_password, new_session, token_hash, verify_password
from app.settings import settings

app = FastAPI(title="软件工程作业系统 API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


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
    item = {"id": str(x.id), "course": x.course, "semester": x.semester, "name": x.name, "invite_code": x.invite_code, "status": x.status, "team_deadline": x.team_deadline, "max_team_members": x.max_team_members, "version": x.version}
    if member_count is not None: item["member_count"] = member_count
    if assignment_count is not None: item["assignment_count"] = assignment_count
    if deletable is not None: item["deletable"] = deletable
    return item


def team_json(db: Session, x: Team, viewer: User):
    leader = db.get(User, x.leader_id)
    count = db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == x.id, TeamMember.status == "ACTIVE")) or 0
    topic = db.scalar(select(Topic).where(Topic.team_id == x.id))
    pending = db.scalar(select(func.count()).select_from(TeamRequest).where(TeamRequest.team_id == x.id, TeamRequest.status == "PENDING")) or 0
    return {"id": str(x.id), "name": x.name, "leader_id": str(x.leader_id), "leader_name": leader.display_name, "member_count": count, "max_members": x.max_members, "open_recruitment": x.open_recruitment, "status": x.status, "is_leader": x.leader_id == viewer.id, "pending_count": pending, "topic": None if not topic else {"id": str(topic.id), "name": topic.name, "description": topic.description, "status": topic.review_status, "reason": topic.review_reason}, "version": x.version}


class LoginIn(BaseModel):
    account: str; password: str; role: Literal["teacher", "student"] | None = None
class ClassIn(BaseModel):
    semester: str = Field(min_length=2, max_length=40); name: str = Field(min_length=2, max_length=100); max_team_members: int = Field(5, ge=2, le=20); team_deadline: datetime | None = None
class TeamIn(BaseModel):
    class_id: UUID; name: str = Field(min_length=2, max_length=40); open_recruitment: bool = True
class TopicIn(BaseModel):
    name: str = Field(min_length=2, max_length=100); description: str = Field("", max_length=1000)
class AssignmentFields(BaseModel):
    title: str = Field(min_length=2, max_length=100); description: str = Field(min_length=1, max_length=5000); submitter_type: Literal["TEAM", "INDIVIDUAL"]; starts_at: datetime | None = None; due_at: datetime; allow_late: bool = False; publish: bool = True
class AssignmentIn(AssignmentFields):
    class_id: UUID
class AssignmentBulkIn(AssignmentFields):
    class_ids: list[UUID] = Field(min_length=1)
class SubmitIn(BaseModel):
    file_ids: list[UUID] = Field(min_length=1, max_length=10)
class CampaignFields(BaseModel):
    rubric: list[dict] = Field(min_length=1, max_length=10); comment_min_length: int = Field(20, ge=0, le=1000); due_at: datetime; publish_at: datetime | None = None; require_all: bool = False; allow_update: bool = True
class CampaignIn(CampaignFields):
    assignment_id: UUID
class CampaignTargetIn(BaseModel):
    class_id: UUID; assignment_id: UUID
class CampaignBulkIn(CampaignFields):
    targets: list[CampaignTargetIn] = Field(min_length=1)
class ReviewIn(BaseModel):
    reviewee_id: UUID; scores: dict[str, float]; comment: str = Field(max_length=2000)
class GradeIn(BaseModel):
    assignment_id: UUID; subject_user_id: UUID | None = None; subject_team_id: UUID | None = None; score: float = Field(ge=0, le=100); comment: str = Field("", max_length=2000); publish: bool = False; reason: str = Field("", max_length=500)
class AssignmentUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=100); description: str | None = Field(None, min_length=1, max_length=5000); starts_at: datetime | None = None; due_at: datetime | None = None; allow_late: bool | None = None; submitter_type: Literal["TEAM", "INDIVIDUAL"] | None = None; version: int
class ReasonIn(BaseModel): reason: str = Field(min_length=2, max_length=500)
class PasswordIn(BaseModel): current_password: str; new_password: str = Field(min_length=8, max_length=128)
class InviteIn(BaseModel): student_id: UUID
class TransferIn(BaseModel): new_leader_id: UUID
class ClassUpdateIn(BaseModel):
    version: int = Field(ge=1)
    semester: str | None = Field(None, min_length=2, max_length=40)
    name: str | None = Field(None, min_length=2, max_length=100)
    team_deadline: datetime | None = None
    max_team_members: int | None = Field(None, ge=2, le=20)
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
    response.delete_cookie("session_id", path="/"); return response


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
    teacher(user); x = TeachingClass(teacher_id=user.id, semester=data.semester.strip(), name=data.name.strip(), invite_code=secrets.token_hex(4).upper(), max_team_members=data.max_team_members, team_deadline=data.team_deadline)
    db.add(x); db.flush(); audit(db, user, "CLASS_CREATED", "class", str(x.id)); db.commit(); return class_json(x)


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
    published = db.scalars(select(Assignment).where(Assignment.class_id == cid, Assignment.status == "PUBLISHED")).all()
    expected = sum(members if item.submitter_type == "INDIVIDUAL" else teams for item in published)
    submitted = db.scalar(select(func.count()).select_from(Submission).join(Assignment).where(Assignment.class_id == cid, Submission.status == "SUBMITTED")) or 0
    eligible_reviewers = db.scalar(select(func.count(func.distinct(TeamMember.user_id))).where(TeamMember.class_id == cid, TeamMember.status == "ACTIVE")) or 0
    reviewers = db.scalar(select(func.count(func.distinct(PeerReview.reviewer_id))).select_from(PeerReview).join(ReviewCampaign).where(ReviewCampaign.class_id == cid, PeerReview.status == "VALID")) or 0
    return {"class": class_json(course), "summary": {"member_count": members, "team_count": teams, "active_assignments": active, "submission_rate": round(submitted * 100 / expected, 1) if expected else 0, "peer_review_rate": round(reviewers * 100 / eligible_reviewers, 1) if eligible_reviewers else 0}}


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
    require_class(db, user, class_id); items = db.scalars(select(Team).where(Team.class_id == class_id, Team.status == "ACTIVE").order_by(Team.created_at)).all(); return {"items": [team_json(db, x, user) for x in items], "total": len(items)}


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
    if user.role == "TEACHER" or membership(db, x.class_id, user.id):
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


def assignment_json(x: Assignment): return {"id": str(x.id), "class_id": str(x.class_id), "title": x.title, "description": x.description, "submitter_type": x.submitter_type, "starts_at": x.starts_at, "due_at": x.due_at, "allow_late": x.allow_late, "status": x.status, "version": x.version}


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
    created = []
    for course in courses:
        item = Assignment(class_id=course.id, title=data.title.strip(), description=data.description, submitter_type=data.submitter_type, starts_at=data.starts_at, due_at=data.due_at, allow_late=data.allow_late, status="PUBLISHED" if data.publish else "DRAFT")
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
    if user.role == "STUDENT": q = q.where(Assignment.status == "PUBLISHED")
    items = db.scalars(q.order_by(Assignment.created_at.desc())).all(); return {"items": [assignment_json(x) for x in items], "total": len(items)}


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
    for key in ("title", "description", "starts_at", "due_at", "allow_late", "submitter_type"):
        value = getattr(data, key)
        if value is not None: setattr(assignment, key, value.strip() if isinstance(value, str) else value)
    assignment.version += 1; audit(db, user, "ASSIGNMENT_UPDATED", "assignment", str(aid)); db.commit(); return assignment_json(assignment)


@app.post("/api/v1/assignments/{aid}/publish")
def publish_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status == "PUBLISHED": return assignment_json(assignment)
    assignment.status = "PUBLISHED"; assignment.version += 1
    for member in db.scalars(select(ClassMember).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE")): notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"新作业：{assignment.title}")
    audit(db, user, "ASSIGNMENT_PUBLISHED", "assignment", str(aid)); db.commit(); return assignment_json(assignment)


def own_submission(db: Session, a: Assignment, user: User):
    if a.submitter_type == "INDIVIDUAL": return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == user.id)), None
    _, x = require_team(db, a.class_id, user); return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_team_id == x.id)), x


@app.post("/api/v1/assignments/{aid}/files", status_code=201)
async def upload(aid: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...)):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, a.class_id)
    team = None
    if user.role == "STUDENT":
        if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
        _, team = require_team(db, a.class_id, user)
    content = await file.read(); suffix = Path(file.filename or "file").suffix.lower()
    if not content or len(content) > 100 * 1024 * 1024: raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空且不得超过 100 MB")
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".md", ".docx", ".pptx", ".xlsx", ".zip"}: raise ApiError(422, "FILE_TYPE_INVALID", "不支持该文件格式")
    fid = uuid4(); relative = f"{aid}/{fid.hex}{suffix}"; target = settings.file_root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    purpose = "ATTACHMENT" if user.role == "TEACHER" else "SUBMISSION"
    team_id = team.id if team and a.submitter_type == "TEAM" else None
    x = FileObject(id=fid, owner_id=user.id, assignment_id=aid, team_id=team_id, purpose=purpose, storage_path=relative, original_name=Path(file.filename or "file").name, size_bytes=len(content), detected_mime=file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream", preview_status="READY" if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".md"} else "PENDING"); db.add(x); db.commit(); return {"id": str(x.id), "name": x.original_name, "size": x.size_bytes, "preview_status": x.preview_status, "purpose": x.purpose, "owner_name": user.display_name, "submitted": False}


@app.get("/api/v1/assignments/{aid}/files")
def assignment_files(aid: UUID, user: CurrentUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    team = require_team(db, assignment.class_id, user)[1] if user.role == "STUDENT" else None
    materials = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT").order_by(FileObject.created_at)).all()
    drafts = []
    if user.role == "STUDENT":
        q = select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION")
        q = q.where(FileObject.owner_id == user.id) if assignment.submitter_type == "INDIVIDUAL" else q.where(FileObject.team_id == team.id)
        drafts = db.scalars(q.order_by(FileObject.created_at)).all()
    def item(file: FileObject):
        linked = bool(db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == file.id).limit(1)))
        owner = db.get(User, file.owner_id)
        return {"id": str(file.id), "name": file.original_name, "size": file.size_bytes, "preview_status": file.preview_status, "owner_name": owner.display_name, "created_at": file.created_at, "submitted": linked}
    return {"attachments": [item(x) for x in materials], "drafts": [item(x) for x in drafts]}


@app.delete("/api/v1/files/{fid}", status_code=204)
def delete_file(fid: UUID, user: CsrfUser, db: Db):
    file = db.get(FileObject, fid); assignment = db.get(Assignment, file.assignment_id) if file else None
    if not file or not assignment: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, assignment.class_id)
    if file.owner_id != user.id: raise ApiError(403, "FILE_FORBIDDEN", "只能删除自己上传的文件")
    if db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == fid).limit(1)): raise ApiError(409, "FILE_ALREADY_SUBMITTED", "正式提交版本中的文件不能删除")
    path = settings.file_root / file.storage_path; db.delete(file); db.commit()
    if path.is_file(): path.unlink()
    return Response(status_code=204)


@app.get("/api/v1/assignments/{aid}/submission")
def submission(aid: UUID, user: CurrentUser, db: Db):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    s, _ = own_submission(db, a, user); versions = db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id).order_by(SubmissionVersion.version_no.desc())).all() if s else []
    result = []
    for version in versions:
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
        result.append({"id": str(version.id), "version_no": version.version_no, "submitted_at": version.submitted_at, "is_late": version.is_late, "member_snapshot": version.member_snapshot, "files": [{"id": str(file.id), "name": file.original_name, "size": file.size_bytes} for file in files]})
    return {"status": s.status if s else "EMPTY", "current_version_no": s.current_version_no if s else 0, "versions": result}


@app.post("/api/v1/assignments/{aid}/submission", status_code=201)
def submit(aid: UUID, data: SubmitIn, user: CsrfUser, db: Db, idempotency_key: Annotated[str | None, Header()] = None):
    a = db.get(Assignment, aid)
    if not a or a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    require_writable_class(db, user, a.class_id)
    s, team = own_submission(db, a, user)
    if team and team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "小组作业仅组长可正式提交")
    if a.due_at < now() and not a.allow_late: raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止且不允许迟交")
    if idempotency_key:
        old = db.scalar(select(SubmissionVersion).where(SubmissionVersion.idempotency_key == idempotency_key))
        if old: return {"id": str(old.id), "version_no": old.version_no, "submitted_at": old.submitted_at, "is_late": old.is_late}
    file_scope = FileObject.owner_id == user.id if not team else FileObject.team_id == team.id
    files = db.scalars(select(FileObject).where(FileObject.id.in_(data.file_ids), FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", file_scope)).all()
    if len(files) != len(set(data.file_ids)): raise ApiError(422, "FILE_OWNERSHIP_INVALID", "文件不存在或不属于当前作业")
    if not s: s = Submission(assignment_id=aid, owner_user_id=user.id if not team else None, owner_team_id=team.id if team else None); db.add(s); db.flush()
    snapshot = {}
    if team:
        rows = db.execute(select(TeamMember, User).join(User).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE").order_by(User.login_name)).all()
        snapshot = {"members": [{"id": str(person.id), "student_no": person.login_name, "name": person.display_name, "role": member.role} for member, person in rows]}
    s.current_version_no += 1; s.status = "SUBMITTED"; v = SubmissionVersion(submission_id=s.id, version_no=s.current_version_no, submitted_by=user.id, member_snapshot=snapshot, is_late=a.due_at < now(), idempotency_key=idempotency_key); db.add(v); db.flush()
    for f in files: db.add(VersionFile(version_id=v.id, file_id=f.id))
    audit(db, user, "SUBMISSION_CREATED", "submission", str(s.id), {"version": v.version_no}); db.commit(); return {"id": str(v.id), "version_no": v.version_no, "submitted_at": v.submitted_at, "is_late": v.is_late}


@app.get("/api/v1/files/{fid}")
def download(fid: UUID, user: CurrentUser, db: Db):
    f = db.get(FileObject, fid); a = db.get(Assignment, f.assignment_id) if f else None
    if not f or not a: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_class(db, user, a.class_id); allowed = user.role == "TEACHER" or f.owner_id == user.id
    if user.role == "STUDENT":
        mine = require_team(db, a.class_id, user)[1]
        if f.purpose == "ATTACHMENT": allowed = True
        elif f.team_id: allowed = f.team_id == mine.id
        elif not allowed:
            owner = membership(db, a.class_id, f.owner_id)
            linked = db.execute(select(SubmissionVersion, Submission).join(Submission, Submission.id == SubmissionVersion.submission_id).join(VersionFile, VersionFile.version_id == SubmissionVersion.id).where(VersionFile.file_id == f.id, Submission.status == "SUBMITTED", Submission.current_version_no == SubmissionVersion.version_no)).first()
            campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == a.id, ReviewCampaign.status == "ACTIVE"))
            allowed = bool(owner and owner[1].id == mine.id and linked and campaign)
    if not allowed: raise ApiError(403, "FILE_FORBIDDEN", "无权访问该文件")
    path = settings.file_root / f.storage_path
    if not path.is_file(): raise ApiError(404, "FILE_MISSING", "文件存储不可用")
    return FileResponse(path, media_type=f.detected_mime, filename=f.original_name)


@app.post("/api/v1/review-campaigns", status_code=201)
def create_campaign(data: CampaignIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.get(Assignment, data.assignment_id)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    courses = writable_teacher_classes(db, user, [assignment.class_id])
    items = create_campaigns_for_targets(data, [CampaignTargetIn(class_id=courses[0].id, assignment_id=assignment.id)], user, db)
    try: db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
    item = items[0]; return {"id": str(item.id), "assignment_id": str(item.assignment_id), "status": item.status}


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
    if user.role == "STUDENT": require_team(db, class_id, user)
    rows = db.execute(select(ReviewCampaign, Assignment).join(Assignment).where(ReviewCampaign.class_id == class_id).order_by(ReviewCampaign.due_at.desc())).all()
    items = [{"id": str(c.id), "assignment_id": str(a.id), "assignment_title": a.title, "rubric": c.rubric, "comment_min_length": c.comment_min_length, "due_at": c.due_at, "publish_at": c.publish_at, "require_all": c.require_all, "allow_update": c.allow_update, "status": c.status, "completed": db.scalar(select(func.count()).select_from(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.status == "VALID")) or 0} for c, a in rows]
    return {"items": items, "total": len(items)}


@app.get("/api/v1/review-campaigns/{cid}/candidates")
def candidates(cid: UUID, user: CurrentUser, db: Db):
    c = db.get(ReviewCampaign, cid)
    if not c: raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    _, team = require_team(db, c.class_id, user); a = db.get(Assignment, c.assignment_id); people = db.scalars(select(User).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE", User.id != user.id)).all(); items = []
    for person in people:
        s = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == person.id, Submission.status == "SUBMITTED")); v = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s else None
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == v.id)).all() if v else []; reviewed = db.scalar(select(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.reviewer_id == user.id, PeerReview.reviewee_id == person.id, PeerReview.status == "VALID"))
        items.append({"user_id": str(person.id), "name": person.display_name, "student_no": person.login_name, "submitted": bool(v), "version_no": v.version_no if v else None, "submitted_at": v.submitted_at if v else None, "files": [{"id": str(f.id), "name": f.original_name, "size": f.size_bytes} for f in files], "reviewed": bool(reviewed), "review": None if not reviewed else {"id": str(reviewed.id), "scores": reviewed.scores, "comment": reviewed.comment, "total_score": reviewed.total_score}})
    return {"items": items, "campaign": {"id": str(c.id), "assignment_title": a.title, "rubric": c.rubric, "comment_min_length": c.comment_min_length, "due_at": c.due_at, "allow_update": c.allow_update}}


@app.post("/api/v1/review-campaigns/{cid}/reviews", status_code=201)
def review(cid: UUID, data: ReviewIn, user: CsrfUser, db: Db):
    c = db.get(ReviewCampaign, cid)
    if not c or c.status != "ACTIVE" or c.due_at < now(): raise ApiError(409, "CAMPAIGN_CLOSED", "互评活动未开放或已截止")
    require_writable_class(db, user, c.class_id)
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
    require_team(db, class_id, user); reviewer = aliased(User)
    rows = db.execute(select(PeerReview, Assignment, reviewer).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment, Assignment.id == ReviewCampaign.assignment_id).join(reviewer, reviewer.id == PeerReview.reviewer_id).where(PeerReview.reviewee_id == user.id, PeerReview.status == "VALID", ReviewCampaign.class_id == class_id, or_(ReviewCampaign.publish_at.is_(None), ReviewCampaign.publish_at <= now()))).all()
    return {"items": [{"id": str(r.id), "assignment_title": a.title, "reviewer_name": p.display_name, "scores": r.scores, "total_score": r.total_score, "comment": r.comment, "created_at": r.created_at} for r, a, p in rows]}


@app.post("/api/v1/peer-reviews/{rid}/invalidate", status_code=204)
def invalidate(rid: UUID, data: ReasonIn, user: CsrfUser, db: Db):
    teacher(user); x = db.get(PeerReview, rid)
    if not x: raise ApiError(404, "REVIEW_NOT_FOUND", "评价不存在")
    campaign = db.get(ReviewCampaign, x.campaign_id)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "REVIEW_NOT_FOUND", "评价不存在")
    require_writable_class(db, user, campaign.class_id)
    x.status, x.invalid_reason = "INVALID", data.reason; audit(db, user, "PEER_REVIEW_INVALIDATED", "peer_review", str(x.id), {"reason": data.reason}); db.commit(); return Response(status_code=204)


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
    metadata_fields = {"semester", "name", "team_deadline", "max_team_members"} & data.model_fields_set
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
    topic.review_status, topic.review_reason = decision, data.reason
    for member in db.scalars(select(TeamMember).where(TeamMember.team_id == topic.team_id, TeamMember.status == "ACTIVE")): notify(db, member.user_id, "TOPIC_DECISION", f"选题审核结果：{decision}")
    audit(db, user, "TOPIC_DECIDED", "topic", str(topic.id), {"decision": decision, "reason": data.reason}); db.commit(); return {"id": str(topic.id), "status": topic.review_status, "reason": topic.review_reason}


@app.post("/api/v1/assignments/{aid}/submission/retract", status_code=204)
def retract(aid: UUID, user: CsrfUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment or assignment.due_at <= now(): raise ApiError(409, "RETRACT_NOT_ALLOWED", "当前不可撤回")
    require_writable_class(db, user, assignment.class_id)
    submission, team = own_submission(db, assignment, user)
    if not submission or submission.status != "SUBMITTED" or (team and team.leader_id != user.id): raise ApiError(403, "RETRACT_NOT_ALLOWED", "无权撤回该提交")
    submission.status = "RETRACTED"; audit(db, user, "SUBMISSION_RETRACTED", "submission", str(submission.id)); db.commit(); return Response(status_code=204)


@app.get("/api/v1/assignments/{aid}/submissions")
def submission_board(aid: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    rows = db.scalars(select(Submission).where(Submission.assignment_id == aid)).all(); items = []
    for s in rows:
        owner = db.get(User, s.owner_user_id) if s.owner_user_id else db.get(Team, s.owner_team_id); latest = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s.current_version_no else None
        items.append({"id": str(s.id), "owner": owner.display_name if isinstance(owner, User) else owner.name, "status": s.status, "version_no": s.current_version_no, "submitted_at": latest.submitted_at if latest else None, "is_late": latest.is_late if latest else False})
    return {"items": items, "total": len(items)}


@app.get("/api/v1/files/{fid}/preview")
def preview_file(fid: UUID, user: CurrentUser, db: Db):
    file = db.get(FileObject, fid)
    if not file: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    response = download(fid, user, db)
    path = settings.file_root / file.storage_path
    if path.suffix.lower() == ".md":
        html = markdown.markdown(path.read_text(encoding="utf-8"), extensions=["fenced_code"])
        clean = bleach.clean(html, tags=["p", "h1", "h2", "h3", "h4", "pre", "code", "ul", "ol", "li", "strong", "em", "blockquote", "a"], attributes={"a": ["href", "title"]}, protocols=["http", "https", "mailto"])
        return HTMLResponse(clean)
    return response


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
            for file in files: archive.write(settings.file_root / file.storage_path, arcname=f"{owner.login_name if isinstance(owner, User) else owner.name}/V{version.version_no}/{file.original_name}")
    audit(db, user, "SUBMISSIONS_EXPORTED", "assignment", str(aid)); db.commit(); return FileResponse(target, media_type="application/zip", filename=f"{assignment.title}.zip")


@app.get("/api/v1/review-campaigns/{cid}/stats")
def campaign_stats(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); campaign = db.get(ReviewCampaign, cid)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    reviews = db.scalars(select(PeerReview).where(PeerReview.campaign_id == cid, PeerReview.status == "VALID")).all()
    reviewers = len({x.reviewer_id for x in reviews}); received_count = {}
    for x in reviews: received_count[str(x.reviewee_id)] = received_count.get(str(x.reviewee_id), 0) + 1
    return {"review_count": len(reviews), "reviewer_count": reviewers, "average_score": round(sum(x.total_score for x in reviews) / len(reviews), 2) if reviews else None, "received_count": received_count}
