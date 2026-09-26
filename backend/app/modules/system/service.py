from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import SessionLocal
from app.models import LoginSession, RoleMenuPermission, User
from app.core.deps import require_class
from app.core.errors import ApiError
from app.core.utils import now

MENU_CATALOG = [
    {"key": "overview", "labels": {"TEACHER": "总览", "STUDENT": "总览"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "classes", "labels": {"TEACHER": "教学班"}, "roles": ["TEACHER"]},
    {"key": "teams", "labels": {"TEACHER": "小组与选题", "STUDENT": "我的小组"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "assignments", "labels": {"TEACHER": "作业管理", "STUDENT": "我的作业"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "reviews", "labels": {"STUDENT": "作品互评"}, "roles": ["STUDENT"]},
    {"key": "capstone", "labels": {"TEACHER": "大作业管理", "STUDENT": "大作业"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "materials", "labels": {"TEACHER": "教学资料", "STUDENT": "教学资料"}, "roles": ["TEACHER", "STUDENT"]},
    {"key": "attendance", "labels": {"TEACHER": "考勤管理"}, "roles": ["TEACHER"]},
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


def _events_authenticate(session_hash: str, class_id: UUID) -> tuple[UUID, str]:
    with SessionLocal() as db:
        login_session = db.scalar(select(LoginSession).where(LoginSession.token_hash == session_hash, LoginSession.revoked_at.is_(None), LoginSession.expires_at > now()))
        user = db.get(User, login_session.user_id) if login_session else None
        if not user or user.status != "ACTIVE": raise ApiError(401, "SESSION_INVALID", "会话已失效")
        require_class(db, user, class_id)
        return user.id, user.role


def _events_session_active(session_hash: str) -> bool:
    with SessionLocal() as session_db:
        return session_db.scalar(select(LoginSession.id).where(LoginSession.token_hash == session_hash, LoginSession.revoked_at.is_(None), LoginSession.expires_at > now()).limit(1)) is not None
