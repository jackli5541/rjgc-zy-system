from __future__ import annotations

import hashlib
import tempfile
from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, File, Response, UploadFile
from pathlib import Path
from sqlalchemy import delete, func, or_, select
from uuid import UUID, uuid4

from app import storage
from app.models import Assignment, FileObject, MarkdownAsset, SubmissionDocument, SubmissionDocumentAsset, SubmissionWorkspace, TeamMember, User
from app.realtime import publish_event
from app.settings import settings
from app.core.audit import audit
from app.core.context import request_client_id
from app.core.deps import CsrfUser, CurrentUser, Db
from app.core.errors import ApiError
from app.core.files import BASE64_IMAGE_PATTERN, MARKDOWN_IMAGE_FORMATS
from app.core.utils import now
from app.modules.assignments.schemas import SubmissionDocumentIn, SubmissionDocumentUpdateIn
from app.modules.assignments.service import check_source_images, document_content_json, document_json, mark_asset_orphan_if_unused, remove_criteria_workspace_documents, require_workspace_document, sync_document_assets, workspace_json, workspace_scope

router = APIRouter()

@router.post("/api/v1/assignments/{aid}/workspace")
def initialize_workspace(aid: UUID, user: CsrfUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    owner_user_id, owner_team_id, _ = workspace_scope(db, assignment, user)
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == owner_user_id)) if owner_user_id else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == owner_team_id))
    if workspace:
        removed_criteria = remove_criteria_workspace_documents(db, workspace)
        if removed_criteria: db.commit()
        return workspace_json(db, workspace, user)
    workspace = SubmissionWorkspace(assignment_id=aid, owner_user_id=owner_user_id, owner_team_id=owner_team_id)
    db.add(workspace); db.flush()
    templates = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT", FileObject.active == True, or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"), FileObject.original_name.like("%.md")).order_by(FileObject.created_at)).all()  # noqa: E712
    used_names = set()
    for index, template in enumerate(templates):
        name = Path(template.original_name).name
        if name.casefold() in used_names:
            name = f"{Path(name).stem}-{index + 1}.md"
        used_names.add(name.casefold())
        db.add(SubmissionDocument(workspace_id=workspace.id, source_file_id=template.id, name=name, markdown_content="", source_images_checked_at=None, sort_order=index, updated_by=user.id))
    audit(db, user, "SUBMISSION_WORKSPACE_CREATED", "submission_workspace", str(workspace.id)); db.commit()
    return workspace_json(db, workspace, user)


@router.post("/api/v1/assignments/{aid}/workspace/documents", status_code=201)
def create_workspace_document(aid: UUID, data: SubmissionDocumentIn, user: CsrfUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    owner_user_id, owner_team_id, _ = workspace_scope(db, assignment, user)
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == owner_user_id)) if owner_user_id else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == owner_team_id))
    if not workspace: raise ApiError(409, "WORKSPACE_REQUIRED", "请先打开在线作业工作区")
    name = Path(data.name.strip()).name
    if not name.lower().endswith(".md"): name += ".md"
    if db.scalar(select(SubmissionDocument.id).where(SubmissionDocument.workspace_id == workspace.id, func.lower(SubmissionDocument.name) == name.lower())): raise ApiError(409, "DOCUMENT_NAME_EXISTS", "同名文档已经存在")
    order = db.scalar(select(func.max(SubmissionDocument.sort_order)).where(SubmissionDocument.workspace_id == workspace.id))
    item = SubmissionDocument(workspace_id=workspace.id, name=name, markdown_content="", source_images_checked_at=now(), sort_order=(order if order is not None else -1) + 1, updated_by=user.id)
    db.add(item); db.commit(); return document_json(db, item)


@router.get("/api/v1/assignments/{aid}/workspace/documents/{document_id}")
def get_workspace_document(aid: UUID, document_id: UUID, user: CurrentUser, db: Db):
    _, workspace, document, _ = require_workspace_document(db, aid, document_id, user)
    if check_source_images(db, workspace, document, user):
        db.commit()
    return document_content_json(db, document)


@router.post("/api/v1/assignments/{aid}/workspace/documents/{document_id}/images", status_code=201)
def upload_workspace_image(aid: UUID, document_id: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...)):
    assignment, workspace, _, _ = require_workspace_document(db, aid, document_id, user)
    asset_id = uuid4()
    temporary = Path(tempfile.gettempdir()) / f"markdown-image-{asset_id.hex}.upload"
    digest = hashlib.sha256()
    size = 0
    storage_path = None
    try:
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.markdown_image_max_bytes:
                    raise ApiError(413, "MARKDOWN_IMAGE_TOO_LARGE", "图片不能超过 10 MB")
                digest.update(chunk)
                output.write(chunk)
        if size == 0:
            raise ApiError(422, "MARKDOWN_IMAGE_EMPTY", "图片内容为空")
        try:
            with Image.open(temporary) as image:
                image_format = image.format
                width, height = image.size
                if image_format not in MARKDOWN_IMAGE_FORMATS:
                    raise ApiError(422, "MARKDOWN_IMAGE_TYPE_INVALID", "仅支持 PNG、JPEG、GIF 或 WebP 图片")
                if width <= 0 or height <= 0 or width * height > settings.markdown_image_max_pixels:
                    raise ApiError(422, "MARKDOWN_IMAGE_DIMENSIONS_INVALID", "图片像素尺寸过大")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ApiError(422, "MARKDOWN_IMAGE_INVALID", "图片内容损坏或格式不受支持")
        suffix, mime_type = MARKDOWN_IMAGE_FORMATS[image_format]
        storage_path = f"markdown-assets/{assignment.id}/{workspace.id}/{asset_id.hex}{suffix}"
        storage.put_object(storage_path, temporary)
        asset = MarkdownAsset(
            id=asset_id, assignment_id=assignment.id, workspace_id=workspace.id, uploader_id=user.id,
            storage_path=storage_path, original_name=Path(file.filename or f"image{suffix}").name,
            mime_type=mime_type, size_bytes=size, sha256=digest.hexdigest(), width=width, height=height,
            orphaned_at=now(),
        )
        db.add(asset)
        try:
            db.commit()
        except Exception:
            db.rollback()
            storage.delete_object(storage_path)
            raise
        return {
            "id": str(asset.id), "url": f"/api/v1/markdown-assets/{asset.id}/content",
            "name": asset.original_name, "mime_type": asset.mime_type, "size_bytes": asset.size_bytes,
            "width": asset.width, "height": asset.height,
        }
    finally:
        file.file.close()
        temporary.unlink(missing_ok=True)


@router.put("/api/v1/assignments/{aid}/workspace/documents/{document_id}")
def update_workspace_document(aid: UUID, document_id: UUID, data: SubmissionDocumentUpdateIn, user: CsrfUser, db: Db):
    assignment, workspace, document, _ = require_workspace_document(db, aid, document_id, user)
    locked = db.scalar(select(SubmissionDocument).where(SubmissionDocument.id == document.id).with_for_update())
    if locked.revision != data.revision:
        raise ApiError(409, "DOCUMENT_VERSION_CONFLICT", f"{db.get(User, locked.updated_by).display_name} 已更新此文档，请刷新后继续", {"document": document_json(db, locked)})
    markdown_content = data.markdown_content.replace("\x00", "")
    if len(markdown_content.encode("utf-8")) > settings.markdown_max_bytes:
        raise ApiError(413, "MARKDOWN_TOO_LARGE", "Markdown 正文不能超过 5 MB")
    if BASE64_IMAGE_PATTERN.search(markdown_content):
        raise ApiError(422, "MARKDOWN_BASE64_IMAGE_FORBIDDEN", "请重新插入图片，Markdown 不再支持 Base64 内嵌图片")
    sync_document_assets(db, assignment, workspace, locked, markdown_content)
    locked.markdown_content = markdown_content
    locked.revision += 1; locked.updated_by = user.id; workspace.updated_at = now()
    audience = [user.id] if workspace.owner_user_id else list(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == workspace.owner_team_id, TeamMember.status == "ACTIVE")))
    publish_event(
        db, class_id=assignment.class_id, scopes=["workspace"], resource_type="submission_document",
        resource_id=document.id, user_ids=audience, roles=["STUDENT"], source_client_id=request_client_id.get(),
        assignment_id=str(assignment.id), workspace_id=str(workspace.id), revision=locked.revision,
    )
    db.commit(); return document_json(db, locked)


@router.delete("/api/v1/assignments/{aid}/workspace/documents/{document_id}", status_code=204)
def delete_workspace_document(aid: UUID, document_id: UUID, user: CsrfUser, db: Db):
    _, workspace, document, _ = require_workspace_document(db, aid, document_id, user)
    if document.source_file_id: raise ApiError(403, "SOURCE_DOCUMENT_DELETE_FORBIDDEN", "教师提供的作业文档不能删除")
    count = db.scalar(select(func.count()).select_from(SubmissionDocument).where(SubmissionDocument.workspace_id == workspace.id)) or 0
    if count <= 1: raise ApiError(409, "LAST_DOCUMENT_REQUIRED", "作业至少需要保留一份 Markdown 文档")
    asset_ids = set(db.scalars(select(SubmissionDocumentAsset.asset_id).where(SubmissionDocumentAsset.document_id == document.id)).all())
    db.execute(delete(SubmissionDocumentAsset).where(SubmissionDocumentAsset.document_id == document.id))
    db.flush()
    for asset in db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(asset_ids))).all() if asset_ids else []:
        mark_asset_orphan_if_unused(db, asset)
    db.delete(document); db.commit(); return Response(status_code=204)
