from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, JSON, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, ForeignKeyConstraint, uuid_pk

class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    submitter_type: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16), default="ASSIGNMENT")
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


class MarkdownAsset(Base):
    __tablename__ = "markdown_assets"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("submission_workspaces.id"), index=True)
    uploader_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    orphaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubmissionDocumentAsset(Base):
    __tablename__ = "submission_document_assets"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("submission_documents.id"), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("markdown_assets.id"), primary_key=True, index=True)


class FileObjectAsset(Base):
    __tablename__ = "file_object_assets"
    file_id: Mapped[UUID] = mapped_column(ForeignKey("file_objects.id"), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("markdown_assets.id"), primary_key=True, index=True)


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
