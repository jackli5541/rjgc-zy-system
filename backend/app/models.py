from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey as SAForeignKey, ForeignKeyConstraint as SAForeignKeyConstraint, Identity, Index, Integer, JSON, Numeric, Unicode as String, UnicodeText as Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def ForeignKey(column: str, **kwargs):
    """Avoid multiple cascade paths, which SQL Server rejects."""
    kwargs.pop("ondelete", None)
    return SAForeignKey(column, **kwargs)


def ForeignKeyConstraint(columns, refcolumns, **kwargs):
    kwargs.pop("ondelete", None)
    return SAForeignKeyConstraint(columns, refcolumns, **kwargs)


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
    topic_public: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeachingMaterialFolder(Base):
    __tablename__ = "teaching_material_folders"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("teaching_material_folders.id"), index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id", "parent_id", "name", name="uq_teaching_material_folder_name"),)


class TeachingMaterial(Base):
    __tablename__ = "teaching_materials"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[UUID | None] = mapped_column(ForeignKey("teaching_material_folders.id"), index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    detected_mime: Mapped[str] = mapped_column(String(100))
    media_type: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
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


class ClassJoinRequest(Base):
    __tablename__ = "class_join_requests"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("uq_pending_class_join_request", ClassJoinRequest.class_id, ClassJoinRequest.user_id, unique=True, mssql_where=ClassJoinRequest.status == "PENDING")


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


Index("uq_team_name", Team.class_id, Team.normalized_name, unique=True, mssql_where=Team.status == "ACTIVE")


class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[UUID] = uuid_pk()
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_active_team_member", TeamMember.class_id, TeamMember.user_id, unique=True, mssql_where=TeamMember.status == "ACTIVE")


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
    auto_review_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_review_mode: Mapped[str | None] = mapped_column(String(16))
    auto_review_criteria_text: Mapped[str | None] = mapped_column(Text)
    auto_review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_review_status: Mapped[str | None] = mapped_column(String(16))
    auto_review_error: Mapped[str | None] = mapped_column(String(500))
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
    material_type: Mapped[str | None] = mapped_column(String(16))
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    detected_mime: Mapped[str] = mapped_column(String(100))
    preview_status: Mapped[str] = mapped_column(String(16), default="READY")
    preview_storage_path: Mapped[str | None] = mapped_column(String(255))
    preview_error: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
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


Index("uq_personal_submission", Submission.assignment_id, Submission.owner_user_id, unique=True, mssql_where=Submission.owner_user_id.is_not(None))
Index("uq_team_submission", Submission.assignment_id, Submission.owner_team_id, unique=True, mssql_where=Submission.owner_team_id.is_not(None))


class SubmissionVersion(Base):
    __tablename__ = "submission_versions"
    id: Mapped[UUID] = uuid_pk()
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    member_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    grade_cap: Mapped[str | None] = mapped_column(String(1))
    __table_args__ = (UniqueConstraint("submission_id", "version_no", name="uq_submission_version"),)


Index("uq_submission_version_idempotency_key", SubmissionVersion.idempotency_key, unique=True, mssql_where=SubmissionVersion.idempotency_key.is_not(None))


class VersionFile(Base):
    __tablename__ = "version_files"
    version_id: Mapped[UUID] = mapped_column(ForeignKey("submission_versions.id", ondelete="CASCADE"), primary_key=True)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("file_objects.id", ondelete="CASCADE"), primary_key=True)


class SubmissionWorkspace(Base):
    __tablename__ = "submission_workspaces"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    owner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


Index("uq_personal_submission_workspace", SubmissionWorkspace.assignment_id, SubmissionWorkspace.owner_user_id, unique=True, mssql_where=SubmissionWorkspace.owner_user_id.is_not(None))
Index("uq_team_submission_workspace", SubmissionWorkspace.assignment_id, SubmissionWorkspace.owner_team_id, unique=True, mssql_where=SubmissionWorkspace.owner_team_id.is_not(None))


class SubmissionDocument(Base):
    __tablename__ = "submission_documents"
    id: Mapped[UUID] = uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("submission_workspaces.id", ondelete="CASCADE"), index=True)
    source_file_id: Mapped[UUID | None] = mapped_column(ForeignKey("file_objects.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    markdown_content: Mapped[str] = mapped_column(Text, default="")
    source_images_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_workspace_document_name"),)


class SubmissionAssessment(Base):
    __tablename__ = "submission_assessments"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    submission_version_id: Mapped[UUID] = mapped_column(ForeignKey("submission_versions.id", ondelete="CASCADE"), index=True)
    evaluator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    subject_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    grade: Mapped[str] = mapped_column(String(1))
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    draft_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("submission_version_id", "evaluator_id", "kind", name="uq_submission_assessment_evaluator"),
    )


class SubmissionAnnotation(Base):
    __tablename__ = "submission_annotations"
    id: Mapped[UUID] = uuid_pk()
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("submission_assessments.id", ondelete="CASCADE"), index=True)
    submission_version_id: Mapped[UUID] = mapped_column(index=True)
    file_id: Mapped[UUID] = mapped_column(index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    mark_type: Mapped[str] = mapped_column(String(20), default="COMMENT")
    color: Mapped[str] = mapped_column(String(10), default="YELLOW")
    anchor: Mapped[dict] = mapped_column(JSON)
    comment: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_version_id", "file_id"],
            ["version_files.version_id", "version_files.file_id"],
            ondelete="CASCADE",
        ),
    )


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
