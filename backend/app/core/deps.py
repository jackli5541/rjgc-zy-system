from __future__ import annotations

import secrets
from fastapi import Cookie, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Annotated
from uuid import UUID

from app.database import get_db
from app.models import ClassMember, LoginSession, TeachingClass, Team, TeamMember, User
from app.security import token_hash
from app.core.errors import ApiError
from app.core.utils import now

Db = Annotated[Session, Depends(get_db)]


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
