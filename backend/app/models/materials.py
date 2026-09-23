from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Unicode as String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class TeachingMaterialFolder(Base):
    __tablename__ = "teaching_material_folders"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("teaching_material_folders.id"), index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
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
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeachingMaterialAsset(Base):
    __tablename__ = "teaching_material_assets"
    id: Mapped[UUID] = uuid_pk()
    material_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_materials.id"), index=True)
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
