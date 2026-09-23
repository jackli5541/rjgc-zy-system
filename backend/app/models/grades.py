from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, Index, Integer, Numeric, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class GradeCoefficient(Base):
    __tablename__ = "grade_coefficients"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    draft_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    published_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("assignment_id", "team_id", name="uq_grade_coefficient_assignment_team"),)


class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("review_campaigns.id", ondelete="CASCADE"), index=True)
    subject_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    coefficient_id: Mapped[UUID | None] = mapped_column(ForeignKey("grade_coefficients.id", ondelete="SET NULL"), index=True)
    peer_review_id: Mapped[UUID | None] = mapped_column(ForeignKey("peer_reviews.id", ondelete="SET NULL"))
    peer_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    draft_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("assignment_id", "subject_user_id", name="uq_personal_grade"),)


Index("uq_grade_peer_review", Grade.peer_review_id, unique=True, mssql_where=Grade.peer_review_id.is_not(None))


class GradeRevision(Base):
    __tablename__ = "grade_revisions"
    id: Mapped[UUID] = uuid_pk()
    grade_id: Mapped[UUID] = mapped_column(ForeignKey("grades.id", ondelete="CASCADE"), index=True)
    changed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    peer_score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    coefficient: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
