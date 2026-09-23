from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, JSON, Unicode as String, UnicodeText as Text, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = uuid_pk()
    login_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoleMenuPermission(Base):
    __tablename__ = "role_menu_permissions"
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    menu_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    rows: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PREVIEWED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(180))
    object_type: Mapped[str | None] = mapped_column(String(32))
    object_id: Mapped[str | None] = mapped_column(String(64))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[UUID] = uuid_pk()
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    class_id: Mapped[UUID | None] = mapped_column(index=True)
    class_semester: Mapped[str | None] = mapped_column(String(40))
    class_name: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(60))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(64))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(40))
    ip_address: Mapped[str | None] = mapped_column(String(45), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(String(255))


class RealtimeEvent(Base):
    __tablename__ = "realtime_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
