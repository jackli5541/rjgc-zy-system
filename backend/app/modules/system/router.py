from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from fastapi import APIRouter, Cookie, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import and_, delete, func, or_, select, text
from typing import Annotated, Literal
from uuid import UUID, uuid4

from app import storage
from app.database import SessionLocal
from app.models import AuditLog, BackgroundJob, LoginSession, Notification, RoleMenuPermission, TeachingClass, User
from app.realtime import hub as realtime_hub, publish_event
from app.security import hash_password, new_session, token_hash, verify_password
from app.settings import settings
from app.core.audit import audit
from app.core.context import request_client_id
from app.core.deps import CsrfUser, CurrentUser, Db, teacher
from app.core.errors import ApiError
from app.core.utils import now
from app.modules.system.schemas import LoginIn, MenuPermissionsIn, PasswordIn
from app.modules.system.service import MENU_CATALOG, _events_authenticate, _events_session_active, menu_permissions_by_role, menu_permissions_payload

router = APIRouter()

@router.get("/api/v1/events")
async def realtime_events(request: Request, class_id: UUID = Query(), session_id: Annotated[str | None, Cookie()] = None):
    session_hash = token_hash(session_id or "")
    user_id, user_role = await asyncio.to_thread(_events_authenticate, session_hash, class_id)
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
                except asyncio.TimeoutError:
                    active = await asyncio.to_thread(_events_session_active, session_hash)
                    if not active:
                        payload = {"id": uuid4().hex, "type": "auth_expired", "scopes": []}
                        yield f"event: auth_expired\nid: {payload['id']}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                        break
                    yield ": heartbeat\n\n"
        finally:
            realtime_hub.unsubscribe(subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/health/live")
def live(): return {"status": "ok", "service": "coursework-api"}


@router.get("/health/ready")
def ready(response: Response):
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        storage.bucket_reachable()
        return {"status": "ready", "database": "ok", "storage": "ok"}
    except Exception:
        response.status_code = 503; return {"status": "not_ready", "database": "unavailable", "storage": "unknown"}


@router.post("/api/v1/auth/login")
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


@router.get("/api/v1/auth/session")
def auth_session(user: CurrentUser, db: Db, session_id: Annotated[str | None, Cookie()] = None):
    x = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id or ""), LoginSession.revoked_at.is_(None)))
    return {"user": {"id": str(user.id), "account": user.login_name, "name": user.display_name, "role": user.role}, "csrf_token": x.csrf_token}


@router.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response, user: CsrfUser, db: Db, session_id: Annotated[str | None, Cookie()] = None):
    x = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(session_id or "")))
    if x: x.revoked_at = now(); db.commit()
    response.delete_cookie("session_id", path="/")
    response.status_code = 204
    return response


@router.post("/api/v1/auth/password", status_code=204)
def password(data: PasswordIn, user: CsrfUser, db: Db):
    if not verify_password(user.password_hash, data.current_password): raise ApiError(422, "CURRENT_PASSWORD_INVALID", "当前密码不正确")
    user.password_hash = hash_password(data.new_password)
    audit(db, user, "PASSWORD_CHANGED", "user", str(user.id))
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()
    return Response(status_code=204)


@router.get("/api/v1/menu-permissions")
def menu_permissions(user: CurrentUser, db: Db):
    return menu_permissions_payload(db, user)


@router.put("/api/v1/menu-permissions")
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


@router.get("/api/v1/export-jobs/{job_id}")
def export_job_status(job_id: UUID, user: CurrentUser, db: Db):
    job = db.get(BackgroundJob, job_id)
    if not job or job.kind != "ARCHIVE_EXPORT" or job.payload.get("requester_id") != str(user.id):
        raise ApiError(404, "EXPORT_JOB_NOT_FOUND", "导出任务不存在")
    status = "PENDING" if job.status == "ARCHIVE_PENDING" else job.status
    return {"id": str(job.id), "status": status, "filename": job.payload.get("filename"), "error": job.last_error if job.status == "FAILED" else None}


@router.get("/api/v1/export-jobs/{job_id}/download")
def download_export_job(job_id: UUID, user: CurrentUser, db: Db):
    job = db.get(BackgroundJob, job_id)
    if not job or job.kind != "ARCHIVE_EXPORT" or job.payload.get("requester_id") != str(user.id):
        raise ApiError(404, "EXPORT_JOB_NOT_FOUND", "导出任务不存在")
    if job.status != "COMPLETED" or not job.result_path:
        raise ApiError(409, "EXPORT_NOT_READY", "导出文件尚未生成")
    if not storage.object_exists(job.result_path):
        raise ApiError(404, "EXPORT_FILE_MISSING", "导出文件已过期")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    return RedirectResponse(storage.sign_get_url(job.result_path, expires), status_code=302, headers={"Cache-Control": "private, no-store"})


@router.get("/api/v1/notifications")
def notifications(user: CurrentUser, db: Db):
    items = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.kind != "SUBMISSION_RESUBMITTED").order_by(Notification.created_at.desc()).limit(100)).all()
    def link(item: Notification) -> str | None:
        if item.object_type == "team" and item.object_id: return f"/teams?team={item.object_id}"
        if item.object_type == "assignment" and item.object_id: return f"/assignments/{item.object_id}?tab=submission"
        return None
    return {"items": [{"id": str(x.id), "title": x.title, "kind": x.kind, "object_type": x.object_type, "object_id": x.object_id, "link": link(x), "read": bool(x.read_at), "created_at": x.created_at} for x in items], "unread": sum(not x.read_at for x in items)}


@router.post("/api/v1/notifications/read", status_code=204)
def read_notifications(user: CsrfUser, db: Db):
    db.execute(Notification.__table__.update().where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=now())); db.commit(); return Response(status_code=204)


@router.get("/api/v1/audit-logs")
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
