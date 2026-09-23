from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

CAPSTONE_STAGES = ("PROPOSAL", "REQUIREMENTS", "DESIGN", "IMPLEMENTATION", "TESTING")


class CapstoneConfig(Base):
    __tablename__ = "capstone_configs"
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), primary_key=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CapstoneUnlock(Base):
    __tablename__ = "capstone_unlocks"
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), primary_key=True)
    student_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    unlocked_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapstoneDocumentTemplate(Base):
    __tablename__ = "capstone_document_templates"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(100))
    markdown_content: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("class_id", "stage", name="uq_capstone_template_class_stage"),)


class CapstoneDocument(Base):
    __tablename__ = "capstone_documents"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    student_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    markdown_content: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    template_id: Mapped[UUID | None] = mapped_column(ForeignKey("capstone_document_templates.id"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CapstoneAsset(Base):
    __tablename__ = "capstone_assets"
    id: Mapped[UUID] = uuid_pk()
    document_id: Mapped[UUID] = mapped_column(ForeignKey("capstone_documents.id"), index=True)
    uploader_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapstoneStageGrade(Base):
    __tablename__ = "capstone_stage_grades"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    student_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    comment: Mapped[str] = mapped_column(Text, default="")
    graded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("class_id", "student_user_id", "stage", name="uq_capstone_grade"),)


class CapstoneModuleAssignment(Base):
    __tablename__ = "capstone_module_assignments"
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), primary_key=True)
    student_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    module_name: Mapped[str] = mapped_column(String(120), default="")
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
