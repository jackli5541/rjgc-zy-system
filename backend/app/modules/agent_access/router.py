"""令牌管理 REST（教师登录态 + CSRF）。MCP 端点见 mcp.py。"""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, teacher
from app.core.errors import ApiError
from app.core.utils import now
from app.models import AgentCallLog, AgentToken, Assignment, TeachingClass
from app.modules.agent_access.schemas import AgentTokenIn, AgentTokenUpdateIn
from app.modules.agent_access.service import ALL_SCOPES, create_token

router = APIRouter()


def token_json(db, item: AgentToken) -> dict:
    since = now() - timedelta(days=7)
    total, failed = db.execute(select(func.count(), func.sum(case((AgentCallLog.status == "FAILED", 1), else_=0))).where(
        AgentCallLog.token_id == item.id, AgentCallLog.created_at >= since)).one()
    status = item.status
    if status == "ACTIVE" and item.expires_at <= now():
        status = "EXPIRED"
    return {
        "id": str(item.id), "name": item.name, "prefix": item.prefix, "scopes": item.scopes,
        "class_ids": item.class_ids, "assignment_ids": item.assignment_ids, "expose_real_name": item.expose_real_name,
        "expires_at": item.expires_at, "status": status, "last_used_at": item.last_used_at, "created_at": item.created_at,
        "calls_7d": total or 0, "failed_7d": int(failed or 0),
    }


def own_token(db, user, token_id: UUID) -> AgentToken:
    item = db.get(AgentToken, token_id)
    if not item or item.owner_user_id != user.id:
        raise ApiError(404, "AGENT_TOKEN_NOT_FOUND", "令牌不存在")
    return item


def check_scope_limits(db, user, class_ids: list[UUID], assignment_ids: list[UUID]) -> None:
    if class_ids:
        owned = set(db.scalars(select(TeachingClass.id).where(TeachingClass.teacher_id == user.id, TeachingClass.id.in_(class_ids))))
        if owned != set(class_ids):
            raise ApiError(422, "CLASS_NOT_OWNED", "包含不属于你的教学班")
    if assignment_ids:
        found = set(db.scalars(select(Assignment.id).join(TeachingClass, TeachingClass.id == Assignment.class_id)
                               .where(TeachingClass.teacher_id == user.id, Assignment.id.in_(assignment_ids))))
        if found != set(assignment_ids):
            raise ApiError(422, "ASSIGNMENT_NOT_OWNED", "包含不属于你的作业")


@router.get("/api/v1/agent-tokens")
def list_tokens(user: CurrentUser, db: Db):
    teacher(user)
    items = db.scalars(select(AgentToken).where(AgentToken.owner_user_id == user.id).order_by(AgentToken.created_at.desc())).all()
    return {"items": [token_json(db, item) for item in items], "scopes": ALL_SCOPES, "endpoint_path": "/mcp"}


@router.post("/api/v1/agent-tokens", status_code=201)
def create_agent_token(data: AgentTokenIn, user: CsrfUser, db: Db):
    teacher(user)
    check_scope_limits(db, user, data.class_ids, data.assignment_ids)
    item, plain = create_token(db, user, name=data.name.strip(), scopes=list(data.scopes), class_ids=[str(x) for x in data.class_ids],
                               assignment_ids=[str(x) for x in data.assignment_ids], expose_real_name=data.expose_real_name, expires_days=data.expires_days)
    audit(db, user, "AGENT_TOKEN_CREATED", "agent_token", str(item.id), {"name": item.name, "scopes": item.scopes})
    db.commit()
    # 明文令牌只在创建时返回这一次。
    return {**token_json(db, item), "token": plain}


@router.put("/api/v1/agent-tokens/{token_id}")
def update_agent_token(token_id: UUID, data: AgentTokenUpdateIn, user: CsrfUser, db: Db):
    teacher(user)
    item = own_token(db, user, token_id)
    if item.status != "ACTIVE":
        raise ApiError(409, "AGENT_TOKEN_REVOKED", "已吊销的令牌不能修改")
    check_scope_limits(db, user, data.class_ids, data.assignment_ids)
    item.name, item.scopes, item.expose_real_name = data.name.strip(), list(data.scopes), data.expose_real_name
    item.class_ids, item.assignment_ids = [str(x) for x in data.class_ids], [str(x) for x in data.assignment_ids]
    if data.expires_days:
        item.expires_at = now() + timedelta(days=data.expires_days)
    audit(db, user, "AGENT_TOKEN_UPDATED", "agent_token", str(item.id), {"name": item.name, "scopes": item.scopes})
    db.commit()
    return token_json(db, item)


@router.post("/api/v1/agent-tokens/{token_id}/revoke")
def revoke_agent_token(token_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    item = own_token(db, user, token_id)
    item.status = "REVOKED"
    audit(db, user, "AGENT_TOKEN_REVOKED", "agent_token", str(item.id), {"name": item.name})
    db.commit()
    return token_json(db, item)


@router.get("/api/v1/agent-calls")
def list_calls(user: CurrentUser, db: Db, token_id: UUID | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    teacher(user)
    query = (select(AgentCallLog, AgentToken.name).join(AgentToken, AgentToken.id == AgentCallLog.token_id)
             .where(AgentToken.owner_user_id == user.id).order_by(AgentCallLog.created_at.desc()).limit(limit))
    if token_id:
        query = query.where(AgentCallLog.token_id == token_id)
    rows = db.execute(query).all()
    return {"items": [{"id": str(log.id), "token_name": name, "tool": log.tool, "status": log.status, "error_code": log.error_code,
                       "latency_ms": log.latency_ms, "ip_address": log.ip_address, "created_at": log.created_at} for log, name in rows]}
