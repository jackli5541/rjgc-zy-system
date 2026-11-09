from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, Unicode as String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import now
from app.database import Base
from app.models._base import ForeignKey, uuid_pk


class AgentToken(Base):
    __tablename__ = "agent_tokens"
    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    class_ids: Mapped[list] = mapped_column(JSON, default=list)
    assignment_ids: Mapped[list] = mapped_column(JSON, default=list)
    expose_real_name: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class AgentClaim(Base):
    __tablename__ = "agent_claims"
    id: Mapped[UUID] = uuid_pk()
    token_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tokens.id"), index=True)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    submission_version_id: Mapped[UUID] = mapped_column(ForeignKey("submission_versions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    release_reason: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


Index("ix_agent_claims_lookup", AgentClaim.assignment_id, AgentClaim.submission_version_id, AgentClaim.status)


class AgentCallLog(Base):
    __tablename__ = "agent_call_logs"
    id: Mapped[UUID] = uuid_pk()
    token_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_tokens.id"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    assignment_id: Mapped[UUID | None] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(60))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), index=True)
