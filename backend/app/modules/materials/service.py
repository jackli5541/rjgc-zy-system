from __future__ import annotations

from sqlalchemy.orm import Session
from uuid import UUID

from app.models import TeachingMaterial, TeachingMaterialFolder, User
from app.core.deps import require_class
from app.core.errors import ApiError

TEACHING_MATERIAL_SUFFIXES = {".md", ".html", ".htm", ".mp4"}
TEACHING_MATERIAL_MIME_TYPES = {
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".html": {"text/html", "text/plain", "application/octet-stream"},
    ".htm": {"text/html", "text/plain", "application/octet-stream"},
    ".mp4": {"video/mp4", "application/octet-stream"},
}


def teaching_material_folder_json(folder: TeachingMaterialFolder) -> dict:
    return {"id": str(folder.id), "parent_id": str(folder.parent_id) if folder.parent_id else None, "name": folder.name, "type": "folder", "sort_order": folder.sort_order}


def teaching_material_json(material: TeachingMaterial) -> dict:
    return {
        "id": str(material.id), "folder_id": str(material.folder_id) if material.folder_id else None,
        "name": material.original_name, "type": "file", "media_type": material.media_type,
        "size": material.size_bytes, "mime": material.detected_mime,
        "content_url": f"/api/v1/teaching-materials/files/{material.id}/content",
        "created_at": material.created_at, "sort_order": material.sort_order,
    }


def require_material_folder(db: Session, user: User, folder_id: UUID, class_id: UUID | None = None) -> TeachingMaterialFolder:
    folder = db.get(TeachingMaterialFolder, folder_id)
    if not folder or (class_id and folder.class_id != class_id):
        raise ApiError(404, "MATERIAL_FOLDER_NOT_FOUND", "鏂囦欢澶逛笉瀛樺湪")
    require_class(db, user, folder.class_id)
    return folder
