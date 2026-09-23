from __future__ import annotations

import mimetypes
import tempfile
from fastapi import APIRouter, File, Query, Response, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from oss2.exceptions import NoSuchKey
from pathlib import Path
from sqlalchemy import func, or_, select
from typing import Literal
from uuid import UUID, uuid4

from app import storage
from app.markdown_assets import extract_assets
from app.models import Assignment, FileObject, FileObjectAsset, MarkdownAsset, User, VersionFile
from app.settings import settings
from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, require_class, require_team, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.files import BASE64_IMAGE_PATTERN, enqueue_archive_export
from app.core.utils import content_disposition, decode_text_file, now
from app.modules.assignments.schemas import MaterialTypeIn
from app.modules.assignments.service import DOWNLOAD_ONLY_FILE_SUFFIXES, PREVIEWABLE_FILE_SUFFIXES, STUDENT_UPLOAD_FILE_SUFFIXES, file_json, own_submission, remove_file_asset_links, require_file_access, require_markdown_asset_access, require_workspace_document, review_config_editable

router = APIRouter()

@router.post("/api/v1/assignments/{aid}/files", status_code=201)
def upload(aid: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...), purpose: Literal["ATTACHMENT", "REVIEW_CRITERIA"] | None = Query(None), material_type: Literal["TASK", "ATTACHMENT", "CRITERIA"] | None = Query(None)):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, a.class_id)
    team = None
    selected_purpose = (purpose or "ATTACHMENT") if user.role == "TEACHER" else "SUBMISSION"
    selected_material_type = (material_type or "ATTACHMENT") if selected_purpose == "ATTACHMENT" else None
    if user.role == "TEACHER" and selected_purpose == "REVIEW_CRITERIA" and not review_config_editable(db, a):
        raise ApiError(409, "AUTO_REVIEW_CONFIG_LOCKED", "作业已截止或互评活动已创建，不能修改互评标准附件")
    if user.role == "STUDENT":
        if a.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续上传附件")
        if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
        if a.starts_at and a.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
        _, team = require_team(db, a.class_id, user)
    suffix = Path(file.filename or "file").suffix.lower()
    if selected_material_type == "CRITERIA" and suffix != ".md":
        raise ApiError(422, "CRITERIA_FILE_TYPE_INVALID", "判定标准仅支持 Markdown 文档")
    supported = STUDENT_UPLOAD_FILE_SUFFIXES if user.role == "STUDENT" else PREVIEWABLE_FILE_SUFFIXES | DOWNLOAD_ONLY_FILE_SUFFIXES
    if suffix not in supported:
        message = "学生提交仅支持 Markdown、HTML、PDF 和常见图片" if user.role == "STUDENT" else "仅支持 Markdown、HTML、PDF、常见图片、Office 文档和 ZIP/RAR/7Z 压缩包"
        raise ApiError(422, "FILE_TYPE_INVALID", message)
    expected_mimes = {
        ".md": {"text/markdown", "text/plain", "application/octet-stream"},
        ".html": {"text/html", "text/plain", "application/octet-stream"}, ".htm": {"text/html", "text/plain", "application/octet-stream"},
        ".pdf": {"application/pdf"},
        ".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"}, ".gif": {"image/gif"}, ".webp": {"image/webp"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        ".zip": {"application/zip", "application/x-zip-compressed"}, ".rar": {"application/vnd.rar", "application/x-rar-compressed"}, ".7z": {"application/x-7z-compressed"},
    }
    if suffix in expected_mimes and file.content_type and file.content_type not in expected_mimes[suffix]:
        raise ApiError(422, "FILE_MIME_INVALID", "文件 MIME 类型与扩展名不匹配")
    fid = uuid4(); relative = f"{aid}/{fid.hex}{suffix}"
    temporary = Path(tempfile.gettempdir()) / f"upload-{fid.hex}{suffix}"
    size = 0
    prepared_assets = []
    uploaded_asset_keys = []
    try:
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空且不得超过 500 MB")
                output.write(chunk)
        if not size: raise ApiError(422, "FILE_SIZE_INVALID", "文件不能为空")
        if suffix == ".md":
            try:
                source = decode_text_file(temporary.read_bytes())
            except UnicodeDecodeError:
                raise ApiError(422, "MARKDOWN_ENCODING_INVALID", "Markdown 文件编码无法识别")
            if BASE64_IMAGE_PATTERN.search(source):
                try:
                    source, prepared_assets = extract_assets(source)
                except ValueError as error:
                    raise ApiError(422, "MARKDOWN_IMAGE_INVALID", str(error))
                if BASE64_IMAGE_PATTERN.search(source):
                    raise ApiError(422, "MARKDOWN_IMAGE_TYPE_INVALID", "Base64 图片仅支持 PNG、JPEG、GIF 或 WebP")
                encoded = source.encode("utf-8")
                if len(encoded) > settings.markdown_max_bytes:
                    raise ApiError(413, "MARKDOWN_TOO_LARGE", "移除图片后的 Markdown 正文不能超过 5 MB")
                for prepared in prepared_assets:
                    asset_key = f"markdown-assets/{aid}/files/{fid}/{prepared.id.hex}{prepared.suffix}"
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
    team_id = team.id if team and a.submitter_type == "TEAM" else None
    preview_status = "READY" if suffix in PREVIEWABLE_FILE_SUFFIXES else "NOT_AVAILABLE"
    x = FileObject(id=fid, owner_id=user.id, assignment_id=aid, team_id=team_id, purpose=selected_purpose, material_type=selected_material_type, storage_path=relative, original_name=Path(file.filename or "file").name, size_bytes=size, detected_mime=file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream", preview_status=preview_status)
    db.add(x)
    pending_asset_ids = []
    for prepared, asset_key in zip(prepared_assets, uploaded_asset_keys):
        db.add(MarkdownAsset(
            id=prepared.id, assignment_id=aid, workspace_id=None, uploader_id=user.id,
            storage_path=asset_key, original_name=f"{Path(x.original_name).stem}-{prepared.id.hex}{prepared.suffix}",
            mime_type=prepared.mime_type, size_bytes=len(prepared.payload), sha256=prepared.sha256,
            width=prepared.width, height=prepared.height, orphaned_at=None,
        ))
        pending_asset_ids.append(prepared.id)
    if pending_asset_ids:
        db.flush()
        for asset_id in pending_asset_ids:
            db.add(FileObjectAsset(file_id=fid, asset_id=asset_id))
    action = "SUBMISSION_FILE_UPLOADED" if selected_purpose == "SUBMISSION" else "ASSIGNMENT_FILE_UPLOADED"
    audit(db, user, action, "assignment", str(aid), {"file_id": str(fid), "original_name": x.original_name})
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete_object(relative)
        for asset_key in uploaded_asset_keys:
            storage.delete_object(asset_key)
        raise
    return file_json(x, user.display_name)


@router.get("/api/v1/assignments/{aid}/files")
def assignment_files(aid: UUID, user: CurrentUser, db: Db):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    team = require_team(db, assignment.class_id, user)[1] if user.role == "STUDENT" else None
    submitted = False
    if user.role == "STUDENT":
        own, _ = own_submission(db, assignment, user)
        submitted = bool(own and own.status == "SUBMITTED")
    material_query = select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT")
    if user.role == "STUDENT" and not submitted:
        material_query = material_query.where(or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"))
    materials = db.scalars(material_query.order_by(FileObject.created_at)).all()
    criteria = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "REVIEW_CRITERIA").order_by(FileObject.created_at)).all()
    drafts = []
    if user.role == "STUDENT":
        q = select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == True)  # noqa: E712
        q = q.where(FileObject.owner_id == user.id) if assignment.submitter_type == "INDIVIDUAL" else q.where(FileObject.team_id == team.id)
        drafts = db.scalars(q.order_by(FileObject.created_at)).all()
    owner_ids = {file.owner_id for file in [*materials, *criteria, *drafts]}
    owners = {owner.id: owner.display_name for owner in db.scalars(select(User).where(User.id.in_(owner_ids))).all()} if owner_ids else {}
    linked_file_ids = set(db.scalars(select(VersionFile.file_id).where(VersionFile.file_id.in_([file.id for file in drafts]))).all()) if drafts else set()
    def item(file: FileObject):
        return file_json(file, owners.get(file.owner_id, ""), file.id in linked_file_ids)
    return {"attachments": [item(x) for x in materials], "review_criteria": [item(x) for x in criteria], "drafts": [item(x) for x in drafts]}


@router.post("/api/v1/files/{fid}/archive", status_code=202)
def queue_file_archive(fid: UUID, user: CsrfUser, db: Db):
    file = require_file_access(db, user, fid)
    if Path(file.original_name).suffix.lower() != ".md":
        raise ApiError(422, "FILE_ARCHIVE_TYPE_INVALID", "仅 Markdown 文件需要生成离线资源包")
    filename = f"{Path(file.original_name).stem}.zip"
    return enqueue_archive_export(db, user, "MATERIALS", {"assignment_id": str(file.assignment_id), "file_ids": [str(fid)]}, filename)


@router.post("/api/v1/assignments/{aid}/workspace/documents/{document_id}/archive", status_code=202)
def queue_workspace_document_archive(aid: UUID, document_id: UUID, user: CsrfUser, db: Db):
    _, _, document, _ = require_workspace_document(db, aid, document_id, user)
    filename = f"{Path(document.name).stem}.zip"
    return enqueue_archive_export(
        db, user, "WORKSPACE_DOCUMENT",
        {"assignment_id": str(aid), "document_id": str(document.id)}, filename,
    )


@router.post("/api/v1/assignments/{aid}/materials.zip", status_code=202)
def queue_assignment_materials(aid: UUID, user: CsrfUser, db: Db, file_ids: list[UUID] = Query(min_length=1, max_length=200)):
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    if user.role == "STUDENT" and assignment.status not in {"PUBLISHED", "CLOSED"}:
        raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可查看的作业不存在")
    files = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.id.in_(file_ids), FileObject.purpose == "ATTACHMENT", FileObject.active == True)).all()  # noqa: E712
    if len(files) != len(set(file_ids)):
        raise ApiError(422, "MATERIAL_FILE_INVALID", "部分文件不存在或不属于该作业资料")
    if user.role == "STUDENT" and any(file.material_type == "CRITERIA" for file in files):
        submission, _ = own_submission(db, assignment, user)
        if not submission or submission.status != "SUBMITTED":
            raise ApiError(403, "CRITERIA_REQUIRES_SUBMISSION", "提交作业后才能查看判定标准")
    return enqueue_archive_export(db, user, "MATERIALS", {"assignment_id": str(aid), "file_ids": [str(item) for item in file_ids]}, "assignment-materials.zip")


@router.delete("/api/v1/files/{fid}", status_code=204)
def delete_file(fid: UUID, user: CsrfUser, db: Db):
    file = db.get(FileObject, fid); assignment = db.get(Assignment, file.assignment_id) if file else None
    if not file or not assignment: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, assignment.class_id)
    if file.owner_id != user.id: raise ApiError(403, "FILE_FORBIDDEN", "只能删除自己上传的文件")
    if file.purpose == "REVIEW_CRITERIA":
        if not review_config_editable(db, assignment):
            raise ApiError(409, "AUTO_REVIEW_CONFIG_LOCKED", "作业已截止或互评活动已创建，不能修改互评标准附件")
        remaining = db.scalar(select(func.count()).select_from(FileObject).where(FileObject.assignment_id == assignment.id, FileObject.purpose == "REVIEW_CRITERIA", FileObject.active == True, FileObject.id != fid)) or 0  # noqa: E712
        if assignment.auto_review_enabled and not (assignment.auto_review_criteria_text or "").strip() and remaining == 0:
            raise ApiError(409, "REVIEW_CRITERIA_REQUIRED", "启用互评时必须保留标准文字或至少一个附件")
    action = "SUBMISSION_FILE_DELETED" if file.purpose == "SUBMISSION" else "ASSIGNMENT_FILE_DELETED"
    if db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == fid).limit(1)):
        file.active = False
        audit(db, user, action, "assignment", str(assignment.id), {"file_id": str(fid), "original_name": file.original_name})
        db.commit()
        return Response(status_code=204)
    key = file.storage_path; original_name = file.original_name
    audit(db, user, action, "assignment", str(assignment.id), {"file_id": str(fid), "original_name": original_name})
    remove_file_asset_links(db, [file.id])
    db.delete(file); db.commit()
    storage.delete_object(key)
    return Response(status_code=204)


@router.patch("/api/v1/files/{fid}")
def retype_file(fid: UUID, body: MaterialTypeIn, user: CsrfUser, db: Db):
    file = db.get(FileObject, fid); assignment = db.get(Assignment, file.assignment_id) if file else None
    if not file or not assignment: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_writable_class(db, user, assignment.class_id)
    if file.owner_id != user.id: raise ApiError(403, "FILE_FORBIDDEN", "只能修改自己上传的文件")
    if file.purpose != "ATTACHMENT": raise ApiError(422, "FILE_TYPE_NOT_APPLICABLE", "只有作业资料附件可以分类")
    if body.material_type == "CRITERIA" and Path(file.original_name).suffix.lower() != ".md":
        raise ApiError(422, "CRITERIA_FILE_TYPE_INVALID", "判定标准仅支持 Markdown 文档")
    file.material_type = body.material_type
    audit(db, user, "ASSIGNMENT_FILE_UPDATED", "assignment", str(assignment.id), {"file_id": str(fid), "material_type": body.material_type})
    db.commit()
    return file_json(file, user.display_name)


@router.get("/api/v1/markdown-assets/{asset_id}/content")
def markdown_asset_content(asset_id: UUID, user: CurrentUser, db: Db):
    asset = require_markdown_asset_access(db, user, asset_id)
    if not storage.object_exists(asset.storage_path):
        raise ApiError(404, "MARKDOWN_ASSET_MISSING", "图片存储不可用")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    return RedirectResponse(storage.sign_get_url(asset.storage_path, expires), status_code=302, headers={"Cache-Control": "private, no-store"})


@router.get("/api/v1/files/{fid}")
def download(fid: UUID, user: CurrentUser, db: Db):
    f = require_file_access(db, user, fid)
    if not storage.object_exists(f.storage_path):
        raise ApiError(404, "FILE_MISSING", "文件存储不可用")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    return RedirectResponse(storage.sign_get_url(f.storage_path, expires), status_code=302, headers={"Cache-Control": "private, no-store"})


@router.get("/api/v1/files/{fid}/preview")
def preview_file(fid: UUID, user: CurrentUser, db: Db):
    file = require_file_access(db, user, fid)
    suffix = Path(file.storage_path).suffix.lower()
    if suffix == ".md":
        try: source = decode_text_file(storage.get_object_bytes(file.storage_path))
        except UnicodeDecodeError: raise ApiError(422, "MARKDOWN_ENCODING_INVALID", "Markdown 文件编码无法识别")
        return PlainTextResponse(source, media_type="text/markdown; charset=utf-8")
    if suffix in {".docx", ".pptx", ".xlsx"}:
        try:
            stream = storage.get_object_stream(file.storage_path)
        except NoSuchKey:
            raise ApiError(404, "FILE_MISSING", "文件存储不可用")
        return StreamingResponse(stream, media_type=file.detected_mime, headers={"Content-Disposition": "inline"})
    try:
        stream = storage.get_object_stream(file.storage_path)
    except NoSuchKey:
        raise ApiError(404, "FILE_MISSING", "文件存储不可用")
    return StreamingResponse(stream, media_type=file.detected_mime, headers={"Content-Disposition": "inline"})


@router.get("/api/v1/files/{fid}/preview-url")
def preview_file_url(fid: UUID, user: CurrentUser, db: Db):
    file = require_file_access(db, user, fid)
    if Path(file.storage_path).suffix.lower() != ".md":
        raise ApiError(422, "FILE_PREVIEW_TYPE_INVALID", "仅 Markdown 文件支持前端直接预览")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    params = {"response-content-disposition": content_disposition(file.original_name, "inline")}
    return {"url": storage.sign_get_url(file.storage_path, expires, params), "expires_in": expires}


@router.get("/api/v1/files/{fid}/render")
def render_file(fid: UUID, user: CurrentUser, db: Db):
    require_file_access(db, user, fid)
    raise ApiError(410, "FILE_RENDER_REMOVED", "Markdown 文件请使用前端预览")


@router.post("/api/v1/assignments/{aid}/download.zip", status_code=202)
def queue_submission_export(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id):
        raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    return enqueue_archive_export(db, user, "ASSIGNMENT", {"assignment_id": str(aid)}, "assignment-submissions.zip")
