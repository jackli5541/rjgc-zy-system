from __future__ import annotations

import mimetypes
import tempfile
from fastapi import APIRouter, File, Query, Response, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pathlib import Path
from sqlalchemy import delete, func, select
from uuid import UUID, uuid4

from app import storage
from app.markdown_assets import extract_assets
from app.models import TeachingMaterial, TeachingMaterialAsset, TeachingMaterialFolder
from app.settings import settings
from app.core.deps import CsrfUser, CurrentUser, Db, require_class, require_writable_class, teacher
from app.core.errors import ApiError
from app.core.files import BASE64_IMAGE_PATTERN
from app.core.utils import content_disposition, decode_text_file
from app.modules.materials.schemas import TeachingMaterialFolderIn, TeachingMaterialMoveIn, TeachingMaterialRenameIn
from app.modules.materials.service import TEACHING_MATERIAL_MIME_TYPES, TEACHING_MATERIAL_SUFFIXES, require_material_folder, teaching_material_folder_json, teaching_material_json

router = APIRouter()

@router.get("/api/v1/teaching-materials")
def teaching_materials(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    folders = db.scalars(select(TeachingMaterialFolder).where(TeachingMaterialFolder.class_id == class_id).order_by(TeachingMaterialFolder.sort_order, TeachingMaterialFolder.name, TeachingMaterialFolder.created_at)).all()
    files = db.scalars(select(TeachingMaterial).where(TeachingMaterial.class_id == class_id, TeachingMaterial.active == True).order_by(TeachingMaterial.sort_order, TeachingMaterial.original_name, TeachingMaterial.created_at)).all()  # noqa: E712
    return {"class_id": str(class_id), "can_manage": user.role == "TEACHER", "folders": [teaching_material_folder_json(item) for item in folders], "files": [teaching_material_json(item) for item in files]}


@router.post("/api/v1/teaching-materials/folders", status_code=201)
def create_teaching_material_folder(data: TeachingMaterialFolderIn, user: CsrfUser, db: Db):
    teacher(user)
    require_writable_class(db, user, data.class_id)
    if data.parent_id:
        parent = require_material_folder(db, user, data.parent_id, data.class_id)
        if parent.class_id != data.class_id:
            raise ApiError(404, "MATERIAL_FOLDER_NOT_FOUND", "鐖剁骇鏂囦欢澶逛笉瀛樺湪")
    name = data.name.strip()
    if not name:
        raise ApiError(422, "MATERIAL_FOLDER_NAME_INVALID", "鏂囦欢澶瑰悕涓嶈兘涓虹┖")
    duplicate = db.scalar(select(TeachingMaterialFolder).where(TeachingMaterialFolder.class_id == data.class_id, TeachingMaterialFolder.parent_id == data.parent_id, TeachingMaterialFolder.name == name))
    if duplicate:
        raise ApiError(409, "MATERIAL_FOLDER_EXISTS", "鍚屼竴鐩綍涓嬪凡瀛樺湪鍚屽悕鏂囦欢澶�")
    next_order = (db.scalar(select(func.max(TeachingMaterialFolder.sort_order)).where(TeachingMaterialFolder.class_id == data.class_id, TeachingMaterialFolder.parent_id == data.parent_id)) or -1) + 1
    folder = TeachingMaterialFolder(class_id=data.class_id, parent_id=data.parent_id, owner_id=user.id, name=name, sort_order=next_order)
    db.add(folder); db.commit(); db.refresh(folder)
    return teaching_material_folder_json(folder)


@router.patch("/api/v1/teaching-materials/folders/{folder_id}")
def rename_teaching_material_folder(folder_id: UUID, data: TeachingMaterialRenameIn, user: CsrfUser, db: Db):
    teacher(user)
    folder = require_material_folder(db, user, folder_id)
    require_writable_class(db, user, folder.class_id)
    name = data.name.strip()
    if not name:
        raise ApiError(422, "MATERIAL_FOLDER_NAME_INVALID", "文件夹名不能为空")
    duplicate = db.scalar(select(TeachingMaterialFolder).where(TeachingMaterialFolder.class_id == folder.class_id, TeachingMaterialFolder.parent_id == folder.parent_id, TeachingMaterialFolder.name == name, TeachingMaterialFolder.id != folder.id))
    if duplicate:
        raise ApiError(409, "MATERIAL_FOLDER_EXISTS", "同一目录下已存在同名文件夹")
    folder.name = name
    db.commit(); db.refresh(folder)
    return teaching_material_folder_json(folder)


@router.post("/api/v1/teaching-materials/folders/{folder_id}/move")
def move_teaching_material_folder(folder_id: UUID, data: TeachingMaterialMoveIn, user: CsrfUser, db: Db):
    teacher(user)
    folder = require_material_folder(db, user, folder_id)
    require_writable_class(db, user, folder.class_id)
    siblings = db.scalars(select(TeachingMaterialFolder).where(TeachingMaterialFolder.class_id == folder.class_id, TeachingMaterialFolder.parent_id == folder.parent_id).order_by(TeachingMaterialFolder.sort_order, TeachingMaterialFolder.name, TeachingMaterialFolder.created_at)).all()
    index = next(i for i, item in enumerate(siblings) if item.id == folder.id)
    neighbor_index = index - 1 if data.direction == "up" else index + 1
    if 0 <= neighbor_index < len(siblings):
        neighbor = siblings[neighbor_index]
        folder.sort_order, neighbor.sort_order = neighbor.sort_order, folder.sort_order
        db.commit(); db.refresh(folder)
    return teaching_material_folder_json(folder)


@router.delete("/api/v1/teaching-materials/folders/{folder_id}", status_code=204)
def delete_teaching_material_folder(folder_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    folder = require_material_folder(db, user, folder_id)
    require_writable_class(db, user, folder.class_id)
    has_child_folder = db.scalar(select(TeachingMaterialFolder.id).where(TeachingMaterialFolder.parent_id == folder.id).limit(1))
    has_file = db.scalar(select(TeachingMaterial.id).where(TeachingMaterial.folder_id == folder.id, TeachingMaterial.active == True).limit(1))  # noqa: E712
    if has_child_folder or has_file:
        raise ApiError(409, "MATERIAL_FOLDER_NOT_EMPTY", "鏂囦欢澶归潪绌猴紝璇峰厛绉婚櫎鍐呭")
    db.delete(folder); db.commit()
    return Response(status_code=204)


@router.post("/api/v1/teaching-materials/files", status_code=201)
def upload_teaching_material(user: CsrfUser, db: Db, class_id: UUID = Query(), folder_id: UUID | None = Query(None), file: UploadFile = File(...)):
    teacher(user)
    require_writable_class(db, user, class_id)
    if folder_id:
        require_material_folder(db, user, folder_id, class_id)
    original_name = Path(file.filename or "file").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in TEACHING_MATERIAL_SUFFIXES:
        raise ApiError(422, "MATERIAL_FILE_TYPE_INVALID", "仅支持 Markdown、HTML 和 MP4 文件")
    if file.content_type and file.content_type not in TEACHING_MATERIAL_MIME_TYPES[suffix]:
        raise ApiError(422, "MATERIAL_FILE_MIME_INVALID", "文件 MIME 类型与扩展名不匹配")
    duplicate = db.scalar(select(TeachingMaterial).where(TeachingMaterial.class_id == class_id, TeachingMaterial.folder_id == folder_id, TeachingMaterial.original_name == original_name, TeachingMaterial.active == True))  # noqa: E712
    if duplicate:
        raise ApiError(409, "MATERIAL_FILE_EXISTS", "同一目录下已存在同名文件")
    material_id = uuid4()
    relative = f"teaching-materials/{class_id}/{material_id.hex}{suffix}"
    temporary = Path(tempfile.gettempdir()) / f"teaching-material-{material_id.hex}{suffix}"
    size = 0
    prepared_assets = []
    uploaded_asset_keys = []
    try:
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise ApiError(422, "FILE_SIZE_INVALID", "文件不能超过 500 MB")
                output.write(chunk)
        if not size:
            raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空")
        if suffix == ".md":
            try:
                source = decode_text_file(temporary.read_bytes())
            except UnicodeDecodeError:
                raise ApiError(422, "MARKDOWN_ENCODING_INVALID", "Markdown 文件编码无法识别")
            if BASE64_IMAGE_PATTERN.search(source):
                try:
                    source, prepared_assets = extract_assets(source, url_for=lambda asset_id: f"/api/v1/teaching-material-assets/{asset_id}/content")
                except ValueError as error:
                    raise ApiError(422, "MATERIAL_IMAGE_INVALID", str(error))
                if BASE64_IMAGE_PATTERN.search(source):
                    raise ApiError(422, "MATERIAL_IMAGE_TYPE_INVALID", "Base64 图片仅支持 PNG、JPEG、GIF、WebP 或 SVG")
                for prepared in prepared_assets:
                    asset_key = f"teaching-materials/{class_id}/assets/{material_id.hex}/{prepared.id.hex}{prepared.suffix}"
                    storage.put_bytes(asset_key, prepared.payload)
                    uploaded_asset_keys.append(asset_key)
            encoded = source.encode("utf-8")
            if len(encoded) > settings.markdown_max_bytes:
                raise ApiError(413, "MARKDOWN_TOO_LARGE", "Markdown 正文不能超过 5 MB")
            temporary.write_bytes(encoded)
            size = len(encoded)
        storage.put_object(relative, temporary)
    except Exception:
        for asset_key in uploaded_asset_keys:
            storage.delete_object(asset_key)
        raise
    finally:
        file.file.close()
        temporary.unlink(missing_ok=True)
    media_type = "MARKDOWN" if suffix == ".md" else "HTML" if suffix in {".html", ".htm"} else "VIDEO"
    next_order = (db.scalar(select(func.max(TeachingMaterial.sort_order)).where(TeachingMaterial.class_id == class_id, TeachingMaterial.folder_id == folder_id, TeachingMaterial.active == True)) or -1) + 1  # noqa: E712
    material = TeachingMaterial(id=material_id, class_id=class_id, folder_id=folder_id, owner_id=user.id, storage_path=relative, original_name=original_name, size_bytes=size, detected_mime=file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream", media_type=media_type, sort_order=next_order)
    db.add(material)
    for prepared, asset_key in zip(prepared_assets, uploaded_asset_keys):
        db.add(TeachingMaterialAsset(
            id=prepared.id, material_id=material_id, storage_path=asset_key,
            original_name=f"{Path(original_name).stem}-{prepared.id.hex}{prepared.suffix}",
            mime_type=prepared.mime_type, size_bytes=len(prepared.payload), sha256=prepared.sha256,
            width=prepared.width, height=prepared.height,
        ))
    db.commit(); db.refresh(material)
    return teaching_material_json(material)


@router.patch("/api/v1/teaching-materials/files/{file_id}")
def rename_teaching_material(file_id: UUID, data: TeachingMaterialRenameIn, user: CsrfUser, db: Db):
    teacher(user)
    material = db.get(TeachingMaterial, file_id)
    if not material or not material.active:
        raise ApiError(404, "MATERIAL_FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, material.class_id)
    stem = data.name.strip()
    if not stem:
        raise ApiError(422, "MATERIAL_FILE_NAME_INVALID", "文件名不能为空")
    name = f"{stem}{Path(material.original_name).suffix}"
    duplicate = db.scalar(select(TeachingMaterial).where(TeachingMaterial.class_id == material.class_id, TeachingMaterial.folder_id == material.folder_id, TeachingMaterial.original_name == name, TeachingMaterial.active == True, TeachingMaterial.id != material.id))  # noqa: E712
    if duplicate:
        raise ApiError(409, "MATERIAL_FILE_EXISTS", "同一目录下已存在同名文件")
    material.original_name = name
    db.commit(); db.refresh(material)
    return teaching_material_json(material)


@router.post("/api/v1/teaching-materials/files/{file_id}/move")
def move_teaching_material(file_id: UUID, data: TeachingMaterialMoveIn, user: CsrfUser, db: Db):
    teacher(user)
    material = db.get(TeachingMaterial, file_id)
    if not material or not material.active:
        raise ApiError(404, "MATERIAL_FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, material.class_id)
    siblings = db.scalars(select(TeachingMaterial).where(TeachingMaterial.class_id == material.class_id, TeachingMaterial.folder_id == material.folder_id, TeachingMaterial.active == True).order_by(TeachingMaterial.sort_order, TeachingMaterial.original_name, TeachingMaterial.created_at)).all()  # noqa: E712
    index = next(i for i, item in enumerate(siblings) if item.id == material.id)
    neighbor_index = index - 1 if data.direction == "up" else index + 1
    if 0 <= neighbor_index < len(siblings):
        neighbor = siblings[neighbor_index]
        material.sort_order, neighbor.sort_order = neighbor.sort_order, material.sort_order
        db.commit(); db.refresh(material)
    return teaching_material_json(material)


@router.delete("/api/v1/teaching-materials/files/{file_id}", status_code=204)
def delete_teaching_material(file_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    material = db.get(TeachingMaterial, file_id)
    if not material or not material.active:
        raise ApiError(404, "MATERIAL_FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, material.class_id)
    key = material.storage_path
    assets = db.scalars(select(TeachingMaterialAsset).where(TeachingMaterialAsset.material_id == material.id)).all()
    asset_keys = [asset.storage_path for asset in assets]
    db.execute(delete(TeachingMaterialAsset).where(TeachingMaterialAsset.material_id == material.id))
    db.delete(material); db.commit()
    storage.delete_object(key)
    for asset_key in asset_keys:
        storage.delete_object(asset_key)
    return Response(status_code=204)


@router.get("/api/v1/teaching-materials/files/{file_id}/content")
def teaching_material_content(file_id: UUID, user: CurrentUser, db: Db, download: bool = Query(False)):
    material = db.get(TeachingMaterial, file_id)
    if not material or not material.active:
        raise ApiError(404, "MATERIAL_FILE_NOT_FOUND", "文件不存在")
    require_class(db, user, material.class_id)
    media_type = {"MARKDOWN": "text/markdown", "HTML": "text/html", "VIDEO": "video/mp4"}[material.media_type]
    disposition = "attachment" if download else "inline"
    return StreamingResponse(storage.get_object_stream(material.storage_path), media_type=media_type, headers={"Content-Disposition": content_disposition(material.original_name, disposition)})


@router.get("/api/v1/teaching-material-assets/{asset_id}/content")
def teaching_material_asset_content(asset_id: UUID, user: CurrentUser, db: Db):
    asset = db.get(TeachingMaterialAsset, asset_id)
    if not asset:
        raise ApiError(404, "MATERIAL_ASSET_NOT_FOUND", "图片不存在")
    material = db.get(TeachingMaterial, asset.material_id)
    if not material:
        raise ApiError(404, "MATERIAL_ASSET_NOT_FOUND", "图片不存在")
    require_class(db, user, material.class_id)
    if not storage.object_exists(asset.storage_path):
        raise ApiError(404, "MATERIAL_ASSET_MISSING", "图片存储不可用")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    params = {"response-content-disposition": content_disposition(asset.original_name, "attachment")} if asset.mime_type == "image/svg+xml" else None
    return RedirectResponse(storage.sign_get_url(asset.storage_path, expires, params), status_code=302, headers={"Cache-Control": "private, no-store"})
