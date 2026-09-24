from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, Index, Integer, LargeBinary, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    code_secret: Mapped[bytes] = mapped_column(LargeBinary(32))
    late_after_minutes: Mapped[int] = mapped_column(Integer, default=10)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


Index("uq_active_attendance_session", AttendanceSession.class_id, unique=True, mssql_where=AttendanceSession.status == "ACTIVE")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id: Mapped[UUID] = uuid_pk()
    session_id: Mapped[UUID] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    student_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    student_no: Mapped[str] = mapped_column(String(64))
    student_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    failed_window_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("session_id", "student_user_id", name="uq_attendance_record_student"),)
