from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class ReviewCampaign(Base):
    __tablename__ = "review_campaigns"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), unique=True)
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str | None] = mapped_column(String(16))
    criteria_text: Mapped[str | None] = mapped_column(Text)
    assignment_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rubric: Mapped[list] = mapped_column(JSON)
    comment_min_length: Mapped[int] = mapped_column(Integer, default=20)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    require_all: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_update: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    grades_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class ReviewAssignment(Base):
    __tablename__ = "review_assignments"
    id: Mapped[UUID] = uuid_pk()
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("review_campaigns.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    participant_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    reviewee_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    submission_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("submission_versions.id"))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    skip_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("campaign_id", "reviewer_id", name="uq_review_assignment_reviewer"),
    )


Index("uq_review_assignment_reviewee", ReviewAssignment.campaign_id, ReviewAssignment.reviewee_id, unique=True, mssql_where=ReviewAssignment.reviewee_id.is_not(None))


class PeerReview(Base):
    __tablename__ = "peer_reviews"
    id: Mapped[UUID] = uuid_pk()
    allocation_id: Mapped[UUID | None] = mapped_column(ForeignKey("review_assignments.id", ondelete="CASCADE"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("review_campaigns.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reviewee_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    submission_version_id: Mapped[UUID] = mapped_column(ForeignKey("submission_versions.id"))
    scores: Mapped[dict] = mapped_column(JSON)
    total_score: Mapped[float] = mapped_column(Float)
    comment: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="VALID")
    invalid_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


Index("uq_valid_peer_review", PeerReview.campaign_id, PeerReview.reviewer_id, PeerReview.reviewee_id, unique=True, mssql_where=PeerReview.status == "VALID")


Index("uq_peer_review_allocation", PeerReview.allocation_id, unique=True, mssql_where=PeerReview.allocation_id.is_not(None))
