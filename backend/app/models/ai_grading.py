from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, JSON, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import now
from app.database import Base
from app.models._base import ForeignKey, uuid_pk


class AiGradingJob(Base):
    __tablename__ = "ai_grading_jobs"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    total_count: Mapped[int] = mapped_column(default=0)
    completed_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), onupdate=now)


class AiGradingDraft(Base):
    __tablename__ = "ai_grading_drafts"
    id: Mapped[UUID] = uuid_pk()
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_grading_jobs.id"), index=True)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    submission_version_id: Mapped[UUID] = mapped_column(ForeignKey("submission_versions.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    assignment_version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default="PROCESSING", index=True)
    model_name: Mapped[str | None] = mapped_column(String(100))
    rubric_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict | None] = mapped_column(JSON)
    suggested_grade: Mapped[str | None] = mapped_column(String(1))
    suggested_comment: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), onupdate=now)
    __table_args__ = (
        UniqueConstraint("submission_version_id", "teacher_id", "status", name="uq_ai_grading_draft_current"),
    )


Index("ix_ai_grading_draft_lookup", AiGradingDraft.assignment_id, AiGradingDraft.submission_version_id, AiGradingDraft.created_at)
