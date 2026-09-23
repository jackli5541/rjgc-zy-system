from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class AttendanceScoreManual(Base):
    """Stopgap manual entry for the 10% attendance component until a real attendance module exists."""
    __tablename__ = "attendance_scores_manual"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    student_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    graded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("class_id", "student_user_id", name="uq_attendance_manual"),)
