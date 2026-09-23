from __future__ import annotations

import hashlib
import tempfile
from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, File, Query, Response, UploadFile
from fastapi.responses import RedirectResponse
from pathlib import Path
from sqlalchemy import func, select
from typing import Literal
from uuid import UUID, uuid4

from app import storage
from app.markdown_assets import extract_assets
from app.models import CAPSTONE_STAGES, CapstoneAsset, CapstoneConfig, CapstoneDocument, CapstoneDocumentTemplate, CapstoneModuleAssignment, CapstoneStageGrade, CapstoneUnlock, ClassMember, Team, TeamMember, Topic, User
from app.settings import settings
from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, membership, require_class, require_writable_class, teacher
from app.core.errors import ApiError
from app.core.files import BASE64_IMAGE_PATTERN, MARKDOWN_IMAGE_FORMATS
from app.core.utils import now
from app.modules.capstone.schemas import CapstoneConfigIn, CapstoneDocumentCreateIn, CapstoneDocumentRenameIn, CapstoneDocumentUpdateIn, CapstoneGradeIn, CapstoneModuleIn
from app.modules.capstone.service import CAPSTONE_STAGE_INFO, CAPSTONE_STAGE_ORDER, capstone_document_content_json, capstone_document_json, capstone_locked, capstone_module_writer, capstone_teammate_ids, capstone_workspace_json, require_capstone_asset_access, require_capstone_document, require_capstone_target_student

router = APIRouter()

@router.post("/api/v1/capstone/classes/{class_id}/workspace")
def initialize_capstone_workspace(class_id: UUID, user: CsrfUser, db: Db, student_id: UUID | None = Query(None)):
    require_class(db, user, class_id)
    target_id = require_capstone_target_student(db, class_id, user, student_id)
    existing_stages = set(db.scalars(select(CapstoneDocument.stage).where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == target_id, CapstoneDocument.active == True)).all())  # noqa: E712
    missing = [stage for stage in CAPSTONE_STAGES if stage not in existing_stages]
    if missing:
        templates = {item.stage: item for item in db.scalars(select(CapstoneDocumentTemplate).where(CapstoneDocumentTemplate.class_id == class_id, CapstoneDocumentTemplate.stage.in_(missing))).all()}
        for stage in missing:
            template = templates.get(stage)
            info = CAPSTONE_STAGE_INFO[stage]
            db.add(CapstoneDocument(
                class_id=class_id, student_user_id=target_id, stage=stage,
                name=template.name if template else info["doc_name"],
                markdown_content=template.markdown_content if template else info["fallback_content"],
                sort_order=0, template_id=template.id if template else None, updated_by=target_id,
            ))
        audit(db, user, "CAPSTONE_WORKSPACE_INITIALIZED", "capstone_workspace", str(target_id), {"class_id": str(class_id)})
        db.commit()
    return capstone_workspace_json(db, class_id, target_id)


@router.post("/api/v1/capstone/classes/{class_id}/workspace/documents", status_code=201)
def create_capstone_document(class_id: UUID, data: CapstoneDocumentCreateIn, user: CsrfUser, db: Db):
    require_class(db, user, class_id)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可新建文档")
    if capstone_locked(db, class_id, user.id): raise ApiError(409, "CAPSTONE_LOCKED", "大作业已截止，无法新建文档")
    name = data.name.strip()
    if not name.lower().endswith(".md"): name += ".md"
    duplicate = db.scalar(select(CapstoneDocument.id).where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == user.id, CapstoneDocument.stage == data.stage, CapstoneDocument.active == True, func.lower(CapstoneDocument.name) == name.lower()))  # noqa: E712
    if duplicate: raise ApiError(409, "CAPSTONE_DOCUMENT_NAME_EXISTS", "同一阶段下已存在同名文档")
    order = db.scalar(select(func.max(CapstoneDocument.sort_order)).where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == user.id, CapstoneDocument.stage == data.stage))
    item = CapstoneDocument(class_id=class_id, student_user_id=user.id, stage=data.stage, name=name, markdown_content="", sort_order=(order if order is not None else -1) + 1, updated_by=user.id)
    db.add(item); db.commit(); db.refresh(item)
    return capstone_document_json(item, user.display_name)


@router.get("/api/v1/capstone/classes/{class_id}/workspace/documents/{document_id}")
def get_capstone_document(class_id: UUID, document_id: UUID, user: CurrentUser, db: Db):
    document = require_capstone_document(db, class_id, document_id, user)
    editor = db.get(User, document.updated_by)
    return capstone_document_content_json(document, editor.display_name if editor else "")


@router.patch("/api/v1/capstone/classes/{class_id}/workspace/documents/{document_id}")
def rename_capstone_document(class_id: UUID, document_id: UUID, data: CapstoneDocumentRenameIn, user: CsrfUser, db: Db):
    document = require_capstone_document(db, class_id, document_id, user, for_write=True)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可重命名文档")
    if capstone_locked(db, class_id, user.id): raise ApiError(409, "CAPSTONE_LOCKED", "大作业已截止，无法修改")
    name = data.name.strip()
    if not name.lower().endswith(".md"): name += ".md"
    duplicate = db.scalar(select(CapstoneDocument.id).where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == user.id, CapstoneDocument.stage == document.stage, CapstoneDocument.active == True, func.lower(CapstoneDocument.name) == name.lower(), CapstoneDocument.id != document.id))  # noqa: E712
    if duplicate: raise ApiError(409, "CAPSTONE_DOCUMENT_NAME_EXISTS", "同一阶段下已存在同名文档")
    document.name = name
    db.commit(); db.refresh(document)
    return capstone_document_json(document, user.display_name)


@router.delete("/api/v1/capstone/classes/{class_id}/workspace/documents/{document_id}", status_code=204)
def delete_capstone_document(class_id: UUID, document_id: UUID, user: CsrfUser, db: Db):
    document = require_capstone_document(db, class_id, document_id, user, for_write=True)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可删除文档")
    if capstone_locked(db, class_id, user.id): raise ApiError(409, "CAPSTONE_LOCKED", "大作业已截止，无法删除")
    count = db.scalar(select(func.count()).select_from(CapstoneDocument).where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == user.id, CapstoneDocument.stage == document.stage, CapstoneDocument.active == True)) or 0
    if count <= 1: raise ApiError(409, "CAPSTONE_LAST_DOCUMENT", "该阶段至少保留一篇文档")
    document.active = False
    db.commit()
    return Response(status_code=204)


@router.put("/api/v1/capstone/classes/{class_id}/workspace/documents/{document_id}")
def update_capstone_document(class_id: UUID, document_id: UUID, data: CapstoneDocumentUpdateIn, user: CsrfUser, db: Db):
    document = require_capstone_document(db, class_id, document_id, user, for_write=True)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可编辑文档")
    if capstone_locked(db, class_id, user.id): raise ApiError(409, "CAPSTONE_LOCKED", "大作业已截止，无法编辑")
    locked = db.scalar(select(CapstoneDocument).where(CapstoneDocument.id == document.id).with_for_update())
    if locked.revision != data.revision:
        editor = db.get(User, locked.updated_by)
        raise ApiError(409, "DOCUMENT_VERSION_CONFLICT", f"{editor.display_name if editor else '其他设备'} 已更新此文档，请刷新后继续", {"document": capstone_document_json(locked, editor.display_name if editor else "")})
    markdown_content = data.markdown_content.replace("\x00", "")
    if BASE64_IMAGE_PATTERN.search(markdown_content):
        try:
            markdown_content, prepared_assets = extract_assets(markdown_content, url_for=lambda asset_id: f"/api/v1/capstone-assets/{asset_id}/content")
        except ValueError as error:
            raise ApiError(422, "MARKDOWN_IMAGE_INVALID", str(error))
        if BASE64_IMAGE_PATTERN.search(markdown_content):
            raise ApiError(422, "MARKDOWN_IMAGE_TYPE_INVALID", "Base64 图片仅支持 PNG、JPEG、GIF、WebP 或 SVG")
        for prepared in prepared_assets:
            asset_key = f"capstone-assets/{class_id}/{document.id}/{prepared.id.hex}{prepared.suffix}"
            storage.put_bytes(asset_key, prepared.payload)
            db.add(CapstoneAsset(
                id=prepared.id, document_id=document.id, uploader_id=user.id, storage_path=asset_key,
                original_name=f"pasted{prepared.suffix}", mime_type=prepared.mime_type, size_bytes=len(prepared.payload),
                sha256=prepared.sha256, width=prepared.width, height=prepared.height,
            ))
    if len(markdown_content.encode("utf-8")) > settings.markdown_max_bytes:
        raise ApiError(413, "MARKDOWN_TOO_LARGE", "Markdown 正文超出大小限制")
    locked.markdown_content = markdown_content
    locked.revision += 1; locked.updated_by = user.id
    db.commit()
    return capstone_document_content_json(locked, user.display_name)


@router.post("/api/v1/capstone/classes/{class_id}/workspace/documents/{document_id}/images", status_code=201)
def upload_capstone_image(class_id: UUID, document_id: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...)):
    document = require_capstone_document(db, class_id, document_id, user, for_write=True)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可上传图片")
    if capstone_locked(db, class_id, user.id): raise ApiError(409, "CAPSTONE_LOCKED", "大作业已截止，无法上传")
    asset_id = uuid4()
    temporary = Path(tempfile.gettempdir()) / f"capstone-image-{asset_id.hex}.upload"
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.markdown_image_max_bytes:
                    raise ApiError(413, "MARKDOWN_IMAGE_TOO_LARGE", "图片超出大小限制")
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
        storage_path = f"capstone-assets/{class_id}/{document.id}/{asset_id.hex}{suffix}"
        storage.put_object(storage_path, temporary)
        asset = CapstoneAsset(
            id=asset_id, document_id=document.id, uploader_id=user.id, storage_path=storage_path,
            original_name=Path(file.filename or f"image{suffix}").name, mime_type=mime_type,
            size_bytes=size, sha256=digest.hexdigest(), width=width, height=height,
        )
        db.add(asset)
        try:
            db.commit()
        except Exception:
            db.rollback()
            storage.delete_object(storage_path)
            raise
        return {
            "id": str(asset.id), "url": f"/api/v1/capstone-assets/{asset.id}/content",
            "name": asset.original_name, "mime_type": asset.mime_type, "size_bytes": asset.size_bytes,
            "width": asset.width, "height": asset.height,
        }
    finally:
        file.file.close()
        temporary.unlink(missing_ok=True)


@router.get("/api/v1/capstone-assets/{asset_id}/content")
def capstone_asset_content(asset_id: UUID, user: CurrentUser, db: Db):
    asset = require_capstone_asset_access(db, user, asset_id)
    if not storage.object_exists(asset.storage_path):
        raise ApiError(404, "CAPSTONE_ASSET_MISSING", "图片存储不可用")
    expires = max(60, min(settings.oss_preview_url_ttl_seconds, 900))
    return RedirectResponse(storage.sign_get_url(asset.storage_path, expires), status_code=302, headers={"Cache-Control": "private, no-store"})


@router.get("/api/v1/capstone/classes/{class_id}/students")
def capstone_students(class_id: UUID, user: CurrentUser, db: Db):
    teacher(user)
    require_class(db, user, class_id)
    members = db.scalars(
        select(User).join(ClassMember, ClassMember.user_id == User.id)
        .where(ClassMember.class_id == class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")
        .order_by(User.login_name)
    ).all()
    grades_by_student: dict[UUID, dict[str, CapstoneStageGrade]] = {}
    for grade in db.scalars(select(CapstoneStageGrade).where(CapstoneStageGrade.class_id == class_id)).all():
        grades_by_student.setdefault(grade.student_user_id, {})[grade.stage] = grade
    unlocked_ids = set(db.scalars(select(CapstoneUnlock.student_user_id).where(CapstoneUnlock.class_id == class_id)).all())
    module_names = {item.student_user_id: item.module_name for item in db.scalars(select(CapstoneModuleAssignment).where(CapstoneModuleAssignment.class_id == class_id)).all()}
    team_topic_rows = db.execute(
        select(TeamMember.user_id, Team.name, Topic.name)
        .join(Team, Team.id == TeamMember.team_id)
        .outerjoin(Topic, Topic.team_id == Team.id)
        .where(TeamMember.class_id == class_id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")
    ).all()
    team_by_student = {user_id: team_name for user_id, team_name, _ in team_topic_rows}
    topic_by_student = {user_id: topic_name for user_id, _, topic_name in team_topic_rows}
    result = []
    for member in members:
        stage_grades = grades_by_student.get(member.id, {})
        result.append({
            "id": str(member.id), "display_name": member.display_name, "login_name": member.login_name,
            "module_name": module_names.get(member.id, ""),
            "team_name": team_by_student.get(member.id, ""),
            "topic_name": topic_by_student.get(member.id, ""),
            "grades": {stage: (float(stage_grades[stage].score) if stage_grades.get(stage) and stage_grades[stage].score is not None else None) for stage in CAPSTONE_STAGES},
            "graded_count": sum(1 for stage in CAPSTONE_STAGES if stage_grades.get(stage) and stage_grades[stage].score is not None),
            "unlocked": member.id in unlocked_ids,
        })
    config = db.get(CapstoneConfig, class_id)
    return {"class_id": str(class_id), "stages": list(CAPSTONE_STAGES), "students": result, "due_at": config.due_at.isoformat() if config and config.due_at else None}


@router.get("/api/v1/capstone/classes/{class_id}/teammates")
def capstone_teammates(class_id: UUID, user: CurrentUser, db: Db):
    require_class(db, user, class_id)
    if user.role != "STUDENT":
        raise ApiError(403, "STUDENT_REQUIRED", "仅学生可查看组内同学")
    row = membership(db, class_id, user.id)
    if not row:
        return {"team_name": None, "topic_name": None, "members": []}
    team = row[1]
    topic = db.scalar(select(Topic).where(Topic.team_id == team.id))
    member_rows = db.execute(
        select(User).join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE")
        .order_by(User.login_name)
    ).scalars().all()
    module_names = {item.student_user_id: item.module_name for item in db.scalars(select(CapstoneModuleAssignment).where(CapstoneModuleAssignment.class_id == class_id, CapstoneModuleAssignment.student_user_id.in_([m.id for m in member_rows]))).all()}
    return {
        "team_name": team.name,
        "topic_name": topic.name if topic else None,
        "members": [{"id": str(member.id), "display_name": member.display_name, "module_name": module_names.get(member.id, ""), "is_self": member.id == user.id} for member in member_rows],
    }


@router.get("/api/v1/capstone/classes/{class_id}/teams/{team_id}/modules")
def capstone_team_modules(class_id: UUID, team_id: UUID, user: CurrentUser, db: Db):
    require_class(db, user, class_id)
    team = db.get(Team, team_id)
    if not team or team.class_id != class_id:
        raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    if user.role == "STUDENT":
        row = membership(db, class_id, user.id)
        if not row or row[1].id != team_id:
            raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    rows = db.scalars(
        select(CapstoneModuleAssignment)
        .where(CapstoneModuleAssignment.class_id == class_id, CapstoneModuleAssignment.student_user_id.in_(select(TeamMember.user_id).where(TeamMember.team_id == team_id, TeamMember.status == "ACTIVE")))
    ).all()
    return {"modules": {str(item.student_user_id): item.module_name for item in rows}}


@router.get("/api/v1/capstone/classes/{class_id}/students/{student_id}/documents")
def capstone_student_documents(class_id: UUID, student_id: UUID, user: CurrentUser, db: Db):
    require_class(db, user, class_id)
    if user.role == "STUDENT" and student_id != user.id and student_id not in capstone_teammate_ids(db, class_id, user.id):
        raise ApiError(404, "STUDENT_NOT_FOUND", "该学生不在本班")
    rows = db.execute(
        select(CapstoneDocument, User.display_name)
        .outerjoin(User, User.id == CapstoneDocument.updated_by)
        .where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == student_id, CapstoneDocument.active == True)  # noqa: E712
        .order_by(CAPSTONE_STAGE_ORDER, CapstoneDocument.sort_order, CapstoneDocument.created_at)
    ).all()
    return {"student_id": str(student_id), "documents": [capstone_document_json(item, editor_name or "") for item, editor_name in rows]}


@router.put("/api/v1/capstone/classes/{class_id}/students/{student_id}/module")
def set_capstone_module(class_id: UUID, student_id: UUID, data: CapstoneModuleIn, user: CsrfUser, db: Db):
    require_writable_class(db, user, class_id)
    if not capstone_module_writer(db, class_id, user, student_id):
        raise ApiError(403, "MODULE_ASSIGN_FORBIDDEN", "仅教师或组长可分配模块名称")
    if not db.scalar(select(ClassMember.id).where(ClassMember.class_id == class_id, ClassMember.user_id == student_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")):
        raise ApiError(404, "STUDENT_NOT_FOUND", "该学生不在本班")
    assignment = db.get(CapstoneModuleAssignment, (class_id, student_id))
    if not assignment:
        assignment = CapstoneModuleAssignment(class_id=class_id, student_user_id=student_id)
        db.add(assignment)
    assignment.module_name = data.module_name.strip()
    assignment.updated_by = user.id
    db.commit()
    return {"class_id": str(class_id), "student_id": str(student_id), "module_name": assignment.module_name}


@router.put("/api/v1/capstone/classes/{class_id}/config")
def update_capstone_config(class_id: UUID, data: CapstoneConfigIn, user: CsrfUser, db: Db):
    teacher(user)
    require_writable_class(db, user, class_id)
    config = db.get(CapstoneConfig, class_id)
    if not config:
        config = CapstoneConfig(class_id=class_id)
        db.add(config)
    config.due_at = data.due_at
    config.updated_by = user.id
    audit(db, user, "CAPSTONE_CONFIG_UPDATED", "capstone_config", str(class_id), {"class_id": str(class_id)})
    db.commit()
    return {"class_id": str(class_id), "due_at": config.due_at.isoformat() if config.due_at else None}


@router.post("/api/v1/capstone/classes/{class_id}/students/{student_id}/unlock", status_code=201)
def unlock_capstone_student(class_id: UUID, student_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    require_writable_class(db, user, class_id)
    if not db.scalar(select(ClassMember.id).where(ClassMember.class_id == class_id, ClassMember.user_id == student_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")):
        raise ApiError(404, "STUDENT_NOT_FOUND", "该学生不在本班")
    if not db.get(CapstoneUnlock, (class_id, student_id)):
        db.add(CapstoneUnlock(class_id=class_id, student_user_id=student_id, unlocked_by=user.id))
        audit(db, user, "CAPSTONE_STUDENT_UNLOCKED", "capstone_unlock", str(student_id), {"class_id": str(class_id)})
        db.commit()
    return {"class_id": str(class_id), "student_id": str(student_id), "unlocked": True}


@router.delete("/api/v1/capstone/classes/{class_id}/students/{student_id}/unlock", status_code=204)
def lock_capstone_student(class_id: UUID, student_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    require_writable_class(db, user, class_id)
    unlock = db.get(CapstoneUnlock, (class_id, student_id))
    if unlock:
        db.delete(unlock)
        audit(db, user, "CAPSTONE_STUDENT_LOCKED", "capstone_unlock", str(student_id), {"class_id": str(class_id)})
        db.commit()
    return Response(status_code=204)


@router.put("/api/v1/capstone/classes/{class_id}/students/{student_id}/grades/{stage}")
def grade_capstone_stage(class_id: UUID, student_id: UUID, stage: Literal["PROPOSAL", "REQUIREMENTS", "DESIGN", "IMPLEMENTATION", "TESTING"], data: CapstoneGradeIn, user: CsrfUser, db: Db):
    teacher(user)
    require_writable_class(db, user, class_id)
    if not db.scalar(select(ClassMember.id).where(ClassMember.class_id == class_id, ClassMember.user_id == student_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")):
        raise ApiError(404, "STUDENT_NOT_FOUND", "该学生不在本班")
    grade = db.scalar(select(CapstoneStageGrade).where(CapstoneStageGrade.class_id == class_id, CapstoneStageGrade.student_user_id == student_id, CapstoneStageGrade.stage == stage))
    if not grade:
        grade = CapstoneStageGrade(class_id=class_id, student_user_id=student_id, stage=stage)
        db.add(grade)
    grade.score = data.score
    grade.comment = data.comment
    grade.graded_by = user.id
    grade.graded_at = now()
    audit(db, user, "CAPSTONE_STAGE_GRADED", "capstone_stage_grade", str(student_id), {"class_id": str(class_id), "stage": stage})
    db.commit(); db.refresh(grade)
    return {"class_id": str(class_id), "student_id": str(student_id), "stage": stage, "score": float(grade.score) if grade.score is not None else None, "comment": grade.comment, "graded_at": grade.graded_at.isoformat() if grade.graded_at else None}
