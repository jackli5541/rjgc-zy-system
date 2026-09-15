from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


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


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeachingClass(Base):
    __tablename__ = "teaching_classes"
    id: Mapped[UUID] = uuid_pk()
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course: Mapped[str] = mapped_column(String(80), default="软件工程")
    semester: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    invite_code: Mapped[str] = mapped_column(String(12), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    team_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_team_members: Mapped[int] = mapped_column(Integer, default=5)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassMember(Base):
    __tablename__ = "class_members"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="STUDENT")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id", "user_id", name="uq_class_member"),)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    rows: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PREVIEWED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    leader_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    normalized_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    open_recruitment: Mapped[bool] = mapped_column(Boolean, default=True)
    max_members: Mapped[int] = mapped_column(Integer, default=5)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id", "normalized_name", name="uq_team_name"),)


class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[UUID] = uuid_pk()
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_active_team_member", TeamMember.class_id, TeamMember.user_id, unique=True, postgresql_where=TeamMember.status == "ACTIVE")


class TeamRequest(Base):
    __tablename__ = "team_requests"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    applicant_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    inviter_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="APPLICATION")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    review_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("class_id", "normalized_name", name="uq_topic_name"),)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    submitter_type: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    allow_late: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileObject(Base):
    __tablename__ = "file_objects"
    id: Mapped[UUID] = uuid_pk()
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    assignment_id: Mapped[UUID | None] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(16), default="SUBMISSION")
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    detected_mime: Mapped[str] = mapped_column(String(100))
    preview_status: Mapped[str] = mapped_column(String(16), default="READY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    owner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    current_version_no: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("assignment_id", "owner_user_id", name="uq_personal_submission"), UniqueConstraint("assignment_id", "owner_team_id", name="uq_team_submission"))


class SubmissionVersion(Base):
    __tablename__ = "submission_versions"
    id: Mapped[UUID] = uuid_pk()
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    member_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    __table_args__ = (UniqueConstraint("submission_id", "version_no", name="uq_submission_version"),)


class VersionFile(Base):
    __tablename__ = "version_files"
    version_id: Mapped[UUID] = mapped_column(ForeignKey("submission_versions.id", ondelete="CASCADE"), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("file_objects.id", ondelete="CASCADE"), primary_key=True)


class ReviewCampaign(Base):
    __tablename__ = "review_campaigns"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), unique=True)
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    rubric: Mapped[list] = mapped_column(JSON)
    comment_min_length: Mapped[int] = mapped_column(Integer, default=20)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    require_all: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_update: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, default=1)


class PeerReview(Base):
    __tablename__ = "peer_reviews"
    id: Mapped[UUID] = uuid_pk()
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


Index("uq_valid_peer_review", PeerReview.campaign_id, PeerReview.reviewer_id, PeerReview.reviewee_id, unique=True, postgresql_where=PeerReview.status == "VALID")


class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    subject_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    subject_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("assignment_id", "subject_user_id", name="uq_personal_grade"), UniqueConstraint("assignment_id", "subject_team_id", name="uq_team_grade"))


class GradeRevision(Base):
    __tablename__ = "grade_revisions"
    id: Mapped[UUID] = uuid_pk()
    grade_id: Mapped[UUID] = mapped_column(ForeignKey("grades.id", ondelete="CASCADE"), index=True)
    changed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    score: Mapped[float] = mapped_column(Float)
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")
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
    action: Mapped[str] = mapped_column(String(60))
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str] = mapped_column(String(64))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(40))
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
