from __future__ import annotations

import re
from oss2.exceptions import OssError
from pathlib import Path
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, load_only
from uuid import UUID

from app import storage
from app.models import Assignment, ClassMember, FileObject, FileObjectAsset, MarkdownAsset, PeerReview, ReviewAssignment, ReviewCampaign, Submission, SubmissionAnnotation, SubmissionAssessment, SubmissionDocument, SubmissionDocumentAsset, SubmissionVersion, SubmissionWorkspace, TeachingClass, Team, TeamMember, User, VersionFile
from app.core.audit import audit, notify
from app.core.deps import membership, require_class, require_team, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.html import clean_html, render_description
from app.core.utils import decode_text_file, now
from app.modules.assignments.schemas import AssignmentFields, SubmissionAnnotationIn, SubmissionFeedbackIn

PREVIEWABLE_FILE_SUFFIXES = {".md"}
DOWNLOAD_ONLY_FILE_SUFFIXES = {".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".docx", ".pptx", ".xlsx", ".zip", ".rar", ".7z"}
STUDENT_UPLOAD_FILE_SUFFIXES = PREVIEWABLE_FILE_SUFFIXES | {".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


MARKDOWN_ASSET_URL_PATTERN = re.compile(r"/api/v1/markdown-assets/([0-9a-fA-F-]{36})/content(?:\?[^\s)\"']*)?")


def assignment_json(x: Assignment): return {"id": str(x.id), "class_id": str(x.class_id), "title": x.title, "description": render_description(x.description), "submitter_type": x.submitter_type, "kind": x.kind, "starts_at": x.starts_at, "due_at": x.due_at, "allow_late": x.allow_late, "auto_review_enabled": x.auto_review_enabled, "auto_review_mode": x.auto_review_mode, "auto_review_criteria_text": x.auto_review_criteria_text or "", "auto_review_due_at": x.auto_review_due_at, "auto_review_status": x.auto_review_status, "auto_review_error": x.auto_review_error, "status": x.status, "version": x.version}


def assignment_progress_json(db: Session, assignment: Assignment) -> dict:
    """Return the teacher-facing workflow counters shown on the assignment list."""
    if assignment.submitter_type == "INDIVIDUAL":
        owner_ids = set(db.scalars(select(ClassMember.user_id).where(
            ClassMember.class_id == assignment.class_id,
            ClassMember.status == "ACTIVE",
            ClassMember.role == "STUDENT",
        )).all())
    else:
        owner_ids = set(db.scalars(select(Team.id).where(
            Team.class_id == assignment.class_id,
            Team.status == "ACTIVE",
        )).all())

    expected_count = len(owner_ids)
    submissions = [item for item in db.scalars(select(Submission).where(
        Submission.assignment_id == assignment.id,
    )).all() if (item.owner_user_id or item.owner_team_id) in owner_ids]
    submitted = [item for item in submissions if item.status == "SUBMITTED" and item.current_version_no]
    submitted_count = len(submitted)

    latest_versions = []
    if submitted:
        version_rows = db.scalars(select(SubmissionVersion).where(
            SubmissionVersion.submission_id.in_([item.id for item in submitted]),
        )).all()
        latest_by_submission = {}
        for version in version_rows:
            current = latest_by_submission.get(version.submission_id)
            if current is None or version.version_no > current.version_no:
                latest_by_submission[version.submission_id] = version
        latest_versions = list(latest_by_submission.values())

    teacher_graded_count = 0
    peer_review_version_ids = set()
    if latest_versions:
        assessments = db.scalars(select(SubmissionAssessment).where(
            SubmissionAssessment.submission_version_id.in_([item.id for item in latest_versions]),
            SubmissionAssessment.status == "PUBLISHED",
        )).all()
        teacher_version_ids = {item.submission_version_id for item in assessments if item.kind == "TEACHER"}
        peer_review_version_ids = {item.submission_version_id for item in assessments if item.kind == "PEER"}
        teacher_graded_count = sum(item.id in teacher_version_ids for item in latest_versions)

    campaign = assignment_review_campaign(db, assignment.id)
    direct_peer_review_count = len(peer_review_version_ids)
    review_enabled = assignment.submitter_type == "INDIVIDUAL" or campaign is not None
    review_assigned_count = 0
    review_completed_count = direct_peer_review_count
    if campaign:
        allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == campaign.id)).all()
        active_allocations = [item for item in allocations if item.status != "SKIPPED"]
        review_assigned_count = len(active_allocations)
        review_completed_count = sum(item.status == "COMPLETED" for item in active_allocations)
        if not review_completed_count:
            review_completed_count = db.scalar(select(func.count(PeerReview.id)).where(
                PeerReview.campaign_id == campaign.id,
                PeerReview.status == "VALID",
            )) or 0
    elif review_enabled:
        # Direct student peer reviews have no campaign/allocation rows. In that
        # mode each submitted work is one review target, so the denominator is
        # the current submitted count.
        review_assigned_count = submitted_count

    if expected_count == 0:
        completion_status = "NO_ROSTER"
    elif submitted_count < expected_count:
        completion_status = "PENDING_SUBMISSION"
    elif review_enabled and review_assigned_count and review_completed_count < review_assigned_count:
        completion_status = "PENDING_REVIEW"
    elif teacher_graded_count < submitted_count:
        completion_status = "PENDING_TEACHER_GRADING"
    else:
        completion_status = "COMPLETED"

    return {
        "expected_count": expected_count,
        "submitted_count": submitted_count,
        "teacher_graded_count": teacher_graded_count,
        "review_enabled": review_enabled,
        "review_assigned_count": review_assigned_count,
        "review_completed_count": review_completed_count,
        "completion_status": completion_status,
    }


def assignment_review_campaign(db: Session, assignment_id: UUID) -> ReviewCampaign | None:
    return db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment_id))


def review_config_editable(db: Session, assignment: Assignment) -> bool:
    return assignment.status != "CLOSED" and assignment.due_at > now() and assignment_review_campaign(db, assignment.id) is None


def has_review_criteria_file(db: Session, assignment_id: UUID) -> bool:
    return bool(db.scalar(select(FileObject.id).where(FileObject.assignment_id == assignment_id, FileObject.purpose == "REVIEW_CRITERIA", FileObject.active == True).limit(1)))  # noqa: E712


def file_json(file: FileObject, owner_name: str | None = None, submitted: bool = False) -> dict:
    suffix = Path(file.original_name).suffix.lower()
    render_type = "RICH_TEXT" if suffix == ".md" else "DOWNLOAD_ONLY"
    previewable = render_type != "DOWNLOAD_ONLY"
    return {"id": str(file.id), "name": file.original_name, "size": file.size_bytes, "render_type": render_type, "preview_status": file.preview_status, "preview_error": file.preview_error, "previewable": previewable, "download_only": not previewable, "purpose": file.purpose, "material_type": file.material_type, "owner_name": owner_name, "created_at": file.created_at, "submitted": submitted}


def writable_teacher_classes(db: Session, user: User, class_ids: list[UUID]) -> list[TeachingClass]:
    teacher(user)
    if len(set(class_ids)) != len(class_ids): raise ApiError(422, "DUPLICATE_CLASS", "教学班不能重复选择")
    courses = db.scalars(select(TeachingClass).where(TeachingClass.id.in_(class_ids), TeachingClass.teacher_id == user.id).with_for_update()).all()
    by_id = {x.id: x for x in courses}
    if len(by_id) != len(class_ids): raise ApiError(404, "CLASS_NOT_FOUND", "部分教学班不存在或无权访问")
    archived = [str(cid) for cid in class_ids if by_id[cid].status != "ACTIVE"]
    if archived: raise ApiError(409, "CLASS_ARCHIVED", "所选教学班中包含已归档班级", {"class_ids": archived})
    return [by_id[cid] for cid in class_ids]


def create_assignments_for_classes(data: AssignmentFields, courses: list[TeachingClass], user: User, db: Session) -> list[Assignment]:
    if data.starts_at and data.starts_at >= data.due_at:
        raise ApiError(422, "ASSIGNMENT_TIME_INVALID", "开始时间必须早于截止时间")
    if data.publish and data.submitter_type == "TEAM" and data.due_at <= now():
        raise ApiError(422, "TEAM_ASSIGNMENT_DUE_INVALID", "小组作业截止时间必须晚于当前时间")
    if data.auto_review_enabled:
        if data.submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "自动互评只能关联个人作业")
        if not data.auto_review_mode or not data.auto_review_due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_REQUIRED", "请完整配置自动互评模式和截止时间")
        if data.auto_review_due_at <= data.due_at: raise ApiError(422, "AUTO_REVIEW_TIME_INVALID", "互评截止时间必须晚于作业截止时间")
        if data.publish and not data.auto_review_criteria_text.strip(): raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "直接发布时必须填写自动互评标准文字")
    created = []
    for course in courses:
        item = Assignment(class_id=course.id, title=data.title.strip(), description=clean_html(data.description), submitter_type=data.submitter_type, kind=data.kind, starts_at=data.starts_at, due_at=data.due_at, allow_late=data.allow_late, auto_review_enabled=data.auto_review_enabled, auto_review_mode=data.auto_review_mode if data.auto_review_enabled else None, auto_review_criteria_text=data.auto_review_criteria_text.strip() if data.auto_review_enabled else None, auto_review_due_at=data.auto_review_due_at if data.auto_review_enabled else None, auto_review_status="PENDING" if data.auto_review_enabled else None, status="PUBLISHED" if data.publish else "DRAFT")
        db.add(item); db.flush(); created.append(item)
        if item.status == "PUBLISHED":
            for member in db.scalars(select(ClassMember).where(ClassMember.class_id == course.id, ClassMember.status == "ACTIVE")): notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"新作业：{item.title}")
        audit(db, user, "ASSIGNMENT_CREATED", "assignment", str(item.id), {"class_id": str(course.id)})
    return created


def own_submission(db: Session, a: Assignment, user: User):
    if a.submitter_type == "INDIVIDUAL": return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_user_id == user.id)), None
    _, x = require_team(db, a.class_id, user); return db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.owner_team_id == x.id)), x


def workspace_scope(db: Session, assignment: Assignment, user: User) -> tuple[UUID | None, UUID | None, Team | None]:
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可编辑作业草稿")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status != "PUBLISHED": raise ApiError(409, "ASSIGNMENT_NOT_WRITABLE", "作业当前不可编辑")
    if assignment.starts_at and assignment.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
    if assignment.due_at < now() and not assignment.allow_late: raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续编辑")
    if assignment.submitter_type == "INDIVIDUAL": return user.id, None, None
    _, team = require_team(db, assignment.class_id, user)
    return None, team.id, team


def document_is_criteria(db: Session, item: SubmissionDocument) -> bool:
    source = db.get(FileObject, item.source_file_id) if item.source_file_id else None
    return bool(source and source.material_type == "CRITERIA")


def document_json(db: Session, item: SubmissionDocument, locked: bool = False, editor_name: str | None = None) -> dict:
    if editor_name is None:
        editor = db.get(User, item.updated_by)
        editor_name = editor.display_name if editor else ""
    return {"id": str(item.id), "name": item.name, "sort_order": item.sort_order, "revision": item.revision, "updated_at": item.updated_at.isoformat() if item.updated_at else None, "updated_by": editor_name, "locked": locked}


def document_content_json(db: Session, item: SubmissionDocument, locked: bool = False) -> dict:
    result = document_json(db, item, locked)
    result["markdown_content"] = "" if locked else item.markdown_content
    return result


def markdown_asset_ids(value: str) -> set[UUID]:
    result = set()
    for raw_id in MARKDOWN_ASSET_URL_PATTERN.findall(value):
        try:
            result.add(UUID(raw_id))
        except ValueError:
            continue
    return result


def mark_asset_orphan_if_unused(db: Session, asset: MarkdownAsset) -> None:
    has_document = db.scalar(select(SubmissionDocumentAsset.asset_id).where(SubmissionDocumentAsset.asset_id == asset.id).limit(1))
    has_file = db.scalar(select(FileObjectAsset.asset_id).where(FileObjectAsset.asset_id == asset.id).limit(1))
    asset.orphaned_at = None if has_document or has_file else (asset.orphaned_at or now())


def remove_file_asset_links(db: Session, file_ids: list[UUID]) -> None:
    if not file_ids:
        return
    asset_ids = set(db.scalars(select(FileObjectAsset.asset_id).where(FileObjectAsset.file_id.in_(file_ids))).all())
    db.execute(delete(FileObjectAsset).where(FileObjectAsset.file_id.in_(file_ids)))
    db.flush()
    if asset_ids:
        for asset in db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(asset_ids))).all():
            mark_asset_orphan_if_unused(db, asset)


def sync_document_assets(db: Session, assignment: Assignment, workspace: SubmissionWorkspace, document: SubmissionDocument, markdown_content: str) -> set[UUID]:
    requested = markdown_asset_ids(markdown_content)
    assets = {item.id: item for item in db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(requested))).all()} if requested else {}
    if set(assets) != requested or any(item.assignment_id != assignment.id for item in assets.values()):
        raise ApiError(422, "MARKDOWN_ASSET_INVALID", "Markdown 中包含不存在或不属于当前作业的图片")
    source_asset_ids = set()
    foreign = [item.id for item in assets.values() if item.workspace_id != workspace.id]
    if foreign:
        source_asset_ids = set(db.scalars(
            select(FileObjectAsset.asset_id)
            .join(FileObject, FileObject.id == FileObjectAsset.file_id)
            .where(
                FileObjectAsset.asset_id.in_(foreign),
                FileObject.assignment_id == assignment.id,
                FileObject.purpose == "ATTACHMENT",
                FileObject.active == True,  # noqa: E712
                or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"),
            )
        ).all())
    if any(item.workspace_id != workspace.id and item.id not in source_asset_ids for item in assets.values()):
        raise ApiError(403, "MARKDOWN_ASSET_FORBIDDEN", "不能引用其他工作区的图片")

    existing = set(db.scalars(select(SubmissionDocumentAsset.asset_id).where(SubmissionDocumentAsset.document_id == document.id)).all())
    for asset_id in requested - existing:
        db.add(SubmissionDocumentAsset(document_id=document.id, asset_id=asset_id))
        assets[asset_id].orphaned_at = None
    removed = existing - requested
    if removed:
        db.execute(delete(SubmissionDocumentAsset).where(SubmissionDocumentAsset.document_id == document.id, SubmissionDocumentAsset.asset_id.in_(removed)))
        db.flush()
        for asset in db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(removed))).all():
            mark_asset_orphan_if_unused(db, asset)
    return requested


def workspace_json(db: Session, workspace: SubmissionWorkspace, user: User) -> dict:
    rows = db.execute(
        select(SubmissionDocument, User.display_name)
        .outerjoin(User, User.id == SubmissionDocument.updated_by)
        .options(load_only(SubmissionDocument.id, SubmissionDocument.name, SubmissionDocument.sort_order, SubmissionDocument.revision, SubmissionDocument.updated_at, SubmissionDocument.updated_by, SubmissionDocument.source_file_id, SubmissionDocument.created_at))
        .where(SubmissionDocument.workspace_id == workspace.id)
        .order_by(SubmissionDocument.sort_order, SubmissionDocument.created_at)
    ).all()
    return {"id": str(workspace.id), "documents": [document_json(db, item, False, editor_name or "") for item, editor_name in rows], "updated_at": workspace.updated_at}


def check_source_images(db: Session, workspace: SubmissionWorkspace, document: SubmissionDocument, user: User) -> bool:
    if document.source_images_checked_at is not None:
        return False
    source_file = db.get(FileObject, document.source_file_id) if document.source_file_id else None
    if not source_file:
        source_file = db.scalar(
            select(FileObject)
            .where(
                FileObject.assignment_id == workspace.assignment_id,
                FileObject.purpose == "ATTACHMENT",
                FileObject.active == True,  # noqa: E712
                or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"),
                func.lower(FileObject.original_name) == document.name.lower(),
            )
            .order_by(FileObject.created_at.desc())
            .limit(1)
        )
    if not source_file:
        document.source_images_checked_at = now()
        return True
    try:
        source = decode_text_file(storage.get_object_bytes(source_file.storage_path))
    except (OssError, UnicodeDecodeError):
        return False
    corrupted_text = "???" in document.name or document.markdown_content.count("?") >= 5
    restored = source if corrupted_text or not document.markdown_content.strip() else restore_embedded_tables(source, restore_embedded_images(source, document.markdown_content))
    changed = restored != document.markdown_content or document.name != Path(source_file.original_name).name or document.source_file_id != source_file.id
    document.source_file_id = source_file.id
    document.name = Path(source_file.original_name).name
    document.markdown_content = restored
    document.source_images_checked_at = now()
    if changed:
        assignment = db.get(Assignment, workspace.assignment_id)
        if assignment:
            sync_document_assets(db, assignment, workspace, document, restored)
        document.revision += 1
        document.updated_by = user.id
    return True


def remove_criteria_workspace_documents(db: Session, workspace: SubmissionWorkspace) -> bool:
    documents = db.scalars(select(SubmissionDocument).join(FileObject, FileObject.id == SubmissionDocument.source_file_id).where(SubmissionDocument.workspace_id == workspace.id, FileObject.material_type == "CRITERIA")).all()
    for document in documents:
        db.delete(document)
    return bool(documents)


def restore_embedded_images(template: str, draft: str) -> str:
    image_source = r"(?:data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+|/api/v1/markdown-assets/[0-9a-fA-F-]{36}/content)"
    image_pattern = re.compile(
        rf"!\[[^\]\r\n]*\]\({image_source}\)"
        rf"|<img\b[^>]*\bsrc\s*=\s*([\"']){image_source}\1[^>]*>",
        re.IGNORECASE,
    )
    source_pattern = re.compile(image_source, re.IGNORECASE)
    result = draft
    for match in image_pattern.finditer(template):
        image_markdown = match.group(0)
        source_url = source_pattern.search(image_markdown)
        if source_url and source_url.group(0) in result: continue
        prefix_lines = [line for line in template[:match.start()].splitlines() if line.strip()]
        anchor = next((line for line in reversed(prefix_lines) if line in result), None)
        if anchor:
            position = result.find(anchor) + len(anchor)
            result = f"{result[:position]}\n\n{image_markdown}{result[position:]}"
        else:
            result = f"{image_markdown}\n\n{result}"
    return result


def markdown_table_blocks(value: str) -> list[tuple[str, list[list[str]]]]:
    def cells(line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"): stripped = stripped[1:]
        if stripped.endswith("|"): stripped = stripped[:-1]
        return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]

    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tables = []
    index = 0
    while index + 1 < len(lines):
        header = cells(lines[index])
        separator = cells(lines[index + 1])
        valid_separator = len(header) >= 2 and len(separator) == len(header) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
        if "|" not in lines[index] or not valid_separator:
            index += 1
            continue
        end = index + 2
        rows = [header]
        while end < len(lines) and "|" in lines[end]:
            row = cells(lines[end])
            if len(row) != len(header): break
            rows.append(row)
            end += 1
        tables.append(("\n".join(lines[index:end]), rows))
        index = end
    return tables


def restore_embedded_tables(template: str, draft: str) -> str:
    result = draft.replace("\r\n", "\n").replace("\r", "\n")
    for table, rows in markdown_table_blocks(template):
        if table in result: continue
        flattened = "".join(cell for row in rows for cell in row)
        if flattened and result.count(flattened) == 1:
            result = result.replace(flattened, table, 1)
    return result


def require_workspace_document(db: Session, aid: UUID, document_id: UUID, user: User) -> tuple[Assignment, SubmissionWorkspace, SubmissionDocument, Team | None]:
    assignment = db.get(Assignment, aid)
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    owner_user_id, owner_team_id, team = workspace_scope(db, assignment, user)
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == owner_user_id)) if owner_user_id else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == owner_team_id))
    document = db.get(SubmissionDocument, document_id)
    if not workspace or not document or document.workspace_id != workspace.id: raise ApiError(404, "DOCUMENT_NOT_FOUND", "在线文档不存在")
    if document_is_criteria(db, document): raise ApiError(403, "CRITERIA_READ_ONLY", "判定标准仅供提交后查看，不能编辑")
    return assignment, workspace, document, team


def latest_personal_submission(db: Session, assignment_id: UUID, user_id: UUID):
    return db.execute(
        select(Submission, SubmissionVersion)
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(Submission.assignment_id == assignment_id, Submission.owner_user_id == user_id, Submission.status == "SUBMITTED")
    ).first()


def require_peer_review_submission(db: Session, assignment_id: UUID, user_id: UUID):
    submitted = latest_personal_submission(db, assignment_id, user_id)
    if not submitted:
        raise ApiError(409, "REVIEWER_SUBMISSION_REQUIRED", "请先提交该作业，再参与互评")
    return submitted


def assessment_payload(item: SubmissionAssessment, evaluator_name: str, annotations: list[dict]) -> dict:
    return {
        "id": str(item.id), "kind": item.kind, "grade": item.grade, "comment": item.comment, "comment_html": item.comment,
        "status": item.status, "version": item.version, "published_at": item.published_at,
        "evaluator_id": str(item.evaluator_id), "evaluator_name": evaluator_name,
        "subject_user_id": str(item.subject_user_id), "submission_version_id": str(item.submission_version_id),
        "annotations": annotations,
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def peer_assessment_summary(db: Session, item: SubmissionAssessment, current_user_id: UUID) -> dict:
    evaluator = db.get(User, item.evaluator_id)
    return {
        "id": str(item.id), "grade": item.grade, "status": item.status, "revision": item.version,
        "published_at": item.published_at, "evaluator_id": str(item.evaluator_id),
        "evaluator_name": evaluator.display_name, "is_current_evaluator": item.evaluator_id == current_user_id,
        "comment": "", "annotations": [], "has_draft": False,
    }


def peer_assessment_for_version(db: Session, version_id: UUID) -> SubmissionAssessment | None:
    return db.scalar(
        select(SubmissionAssessment)
        .where(SubmissionAssessment.submission_version_id == version_id, SubmissionAssessment.kind == "PEER")
        .order_by(SubmissionAssessment.created_at, SubmissionAssessment.id)
    )


def lock_submission_version(db: Session, version_id: UUID) -> None:
    query = (
        select(SubmissionVersion.id)
        .where(SubmissionVersion.id == version_id)
        .with_for_update()
        .with_hint(SubmissionVersion, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql")
    )
    db.scalar(query)


def assessment_json(db: Session, item: SubmissionAssessment) -> dict:
    evaluator = db.get(User, item.evaluator_id)
    return assessment_payload(item, evaluator.display_name, assessment_annotations(db, item.id))


GRADE_POINTS = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
POINT_GRADES = {value: key for key, value in GRADE_POINTS.items()}


def build_submission_grade_result(assessments: list[SubmissionAssessment], serialize_assessment) -> dict:
    teacher_assessment = next((item for item in assessments if item.kind == "TEACHER" and item.status == "PUBLISHED"), None)
    peer_assessments = [item for item in assessments if item.kind == "PEER" and item.status == "PUBLISHED"]
    peer_grade = None
    if peer_assessments:
        average = sum(GRADE_POINTS[item.grade] for item in peer_assessments) / len(peer_assessments)
        peer_grade = POINT_GRADES[int(average + 0.5)]
    final_grade = teacher_assessment.grade if teacher_assessment else peer_grade
    return {
        "teacher_grade": serialize_assessment(teacher_assessment) if teacher_assessment else None,
        "peer_grade": peer_grade, "peer_review_count": len(peer_assessments),
        "peer_feedbacks": [serialize_assessment(item) for item in peer_assessments],
        "final_grade": final_grade, "grade_source": "TEACHER" if teacher_assessment else "PEER" if peer_grade else None,
        "grading_status": "GRADED" if final_grade else "PENDING_ASSESSMENT",
    }


GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


def assert_submission_update_allowed(db: Session, submission: Submission, current: SubmissionVersion | None) -> None:
    if not current:
        return
    result = submission_grade_result(db, current)
    final_grade = result.get("final_grade")
    if final_grade is None:
        raise ApiError(409, "SUBMISSION_UPDATE_LOCKED", "提交后需要等待互评完成或教师评分后，才能重新提交")
    if GRADE_RANK.get(final_grade, 0) > GRADE_RANK["C"]:
        raise ApiError(409, "SUBMISSION_UPDATE_LOCKED", "最终成绩为 A 或 B，不能更新提交")


def submission_grade_result(db: Session, version: SubmissionVersion) -> dict:
    assessments = list(db.scalars(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id)).all())
    return build_submission_grade_result(assessments, lambda item: assessment_json(db, item))


def displayed_submission_grade_result(db: Session, version: SubmissionVersion, current_result: dict | None = None) -> dict:
    result = current_result or submission_grade_result(db, version)
    if result.get("final_grade") or version.version_no <= 1:
        return {**result, "grade_carried_forward": False, "grade_from_version_no": version.version_no if result.get("final_grade") else None}
    previous_versions = db.scalars(
        select(SubmissionVersion)
        .where(SubmissionVersion.submission_id == version.submission_id, SubmissionVersion.version_no < version.version_no)
        .order_by(SubmissionVersion.version_no.desc())
    ).all()
    for previous in previous_versions:
        previous_result = submission_grade_result(db, previous)
        if previous_result.get("final_grade"):
            return {
                **previous_result,
                "grading_status": "PENDING_REASSESSMENT",
                "grade_carried_forward": True,
                "grade_from_version_no": previous.version_no,
            }
    return {**result, "grade_carried_forward": False, "grade_from_version_no": None}


def missing_submission_grade_result(assignment: Assignment) -> dict:
    overdue = assignment.status in {"PUBLISHED", "CLOSED"} and assignment.due_at <= now()
    return {
        "teacher_grade": None, "peer_grade": None, "peer_review_count": 0, "peer_feedbacks": [],
        "final_grade": "E" if overdue else None, "grade_source": "SYSTEM" if overdue else None,
        "grading_status": "NO_SUBMISSION" if overdue else "PENDING_SUBMISSION",
    }


def feedback_context(db: Session, version_id: UUID, user: User):
    row = db.execute(
        select(SubmissionVersion, Submission, Assignment)
        .join(Submission, Submission.id == SubmissionVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(SubmissionVersion.id == version_id)
    ).first()
    if not row: raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    version, submission_item, assignment = row
    if user.role == "TEACHER":
        if not user_class(db, user, assignment.class_id): raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    elif submission_item.owner_user_id != user.id:
        team_row = membership(db, assignment.class_id, user.id) if submission_item.owner_team_id else None
        if not team_row or team_row[1].id != submission_item.owner_team_id:
            raise ApiError(403, "FEEDBACK_FORBIDDEN", "无权查看该提交反馈")
    return version, submission_item, assignment


def annotation_json(item: SubmissionAnnotation) -> dict:
    mark_type = item.mark_type or ("COMMENT" if item.comment else "HIGHLIGHT")
    return {"id": str(item.id), "file_id": str(item.file_id), "kind": item.kind, "mark_type": mark_type, "color": item.color or "YELLOW", "anchor": item.anchor, "comment": item.comment, "created_at": item.created_at, "updated_at": item.updated_at}


def assessment_annotations(db: Session, assessment_id: UUID) -> list[dict]:
    items = db.scalars(select(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == assessment_id).order_by(SubmissionAnnotation.position, SubmissionAnnotation.created_at)).all()
    return [annotation_json(item) for item in items]


def feedback_json(db: Session, item: SubmissionAssessment | None, include_draft: bool = False) -> dict:
    if not item:
        return {"status": None, "revision": 0, "grade": None, "comment": "", "annotations": [], "published_at": None, "has_draft": False}
    published = {"grade": item.grade, "comment": item.comment, "annotations": assessment_annotations(db, item.id)}
    draft = item.draft_payload if include_draft and item.draft_payload else None
    payload = draft or published
    return {
        "id": str(item.id), "status": "DRAFT" if draft or item.status == "DRAFT" else "PUBLISHED",
        "published_status": item.status, "revision": item.version, "published_at": item.published_at,
        "has_draft": bool(draft), "grade": payload["grade"], "comment": payload.get("comment", ""),
        "annotations": payload.get("annotations", []),
    }


def validate_feedback_annotations(db: Session, version_id: UUID, annotations: list[SubmissionAnnotationIn]) -> list[dict]:
    payload = []
    for annotation in annotations:
        linked = db.scalar(select(VersionFile.file_id).where(VersionFile.version_id == version_id, VersionFile.file_id == annotation.file_id))
        file = db.get(FileObject, annotation.file_id) if linked else None
        if not file: raise ApiError(422, "ANNOTATION_FILE_INVALID", "批注文件不属于该提交版本")
        suffix = Path(file.original_name).suffix.lower()
        anchor = annotation.anchor
        cleaned_comment = clean_html(annotation.comment)
        mark_type = annotation.mark_type or ("COMMENT" if annotation.comment.strip() else "HIGHLIGHT")
        if annotation.kind == "PDF_TEXT_OR_REGION":
            rects = anchor.get("rects") if isinstance(anchor, dict) else None
            if suffix != ".pdf" or not isinstance(anchor.get("page"), int) or anchor["page"] < 1 or not isinstance(rects, list) or not rects or len(rects) > 100:
                raise ApiError(422, "ANNOTATION_ANCHOR_INVALID", "PDF 批注锚点无效")
            for rect in rects:
                if not isinstance(rect, dict) or any(not isinstance(rect.get(key), (int, float)) for key in ("x", "y", "width", "height")) or rect["width"] <= 0 or rect["height"] <= 0 or any(rect[key] < 0 or rect[key] > 1 for key in ("x", "y", "width", "height")) or rect["x"] + rect["width"] > 1.001 or rect["y"] + rect["height"] > 1.001:
                    raise ApiError(422, "ANNOTATION_ANCHOR_INVALID", "PDF 批注坐标无效")
            if not str(anchor.get("quote", "")).strip() and mark_type not in {"HIGHLIGHT", "COMMENT"}:
                raise ApiError(422, "ANNOTATION_MARK_TYPE_INVALID", "PDF 区域批注仅支持高亮或评论")
        else:
            start, end = anchor.get("start") if isinstance(anchor, dict) else None, anchor.get("end") if isinstance(anchor, dict) else None
            valid_point = lambda point: isinstance(point, dict) and isinstance(point.get("block_id"), str) and bool(re.fullmatch(r"b\d+", point["block_id"])) and isinstance(point.get("offset"), int) and point["offset"] >= 0
            if suffix not in {".md", ".html", ".htm"} or not valid_point(start) or not valid_point(end) or len(str(anchor.get("exact", ""))) > 4000:
                raise ApiError(422, "ANNOTATION_ANCHOR_INVALID", "富文本批注锚点无效")
        payload.append({"id": str(annotation.id) if annotation.id else None, "file_id": str(annotation.file_id), "kind": annotation.kind, "mark_type": mark_type, "color": annotation.color, "anchor": anchor, "comment": cleaned_comment})
    return payload


def replace_feedback_annotations(db: Session, item: SubmissionAssessment, annotations: list[dict], user: User) -> None:
    db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == item.id))
    for position, annotation in enumerate(annotations):
        db.add(SubmissionAnnotation(assessment_id=item.id, submission_version_id=item.submission_version_id, file_id=UUID(annotation["file_id"]), author_id=user.id, kind=annotation["kind"], mark_type=annotation.get("mark_type") or ("COMMENT" if annotation.get("comment") else "HIGHLIGHT"), color=annotation.get("color") or "YELLOW", anchor=annotation["anchor"], comment=annotation["comment"], position=position))


def peer_feedback_context(db: Session, version_id: UUID, user: User):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    row = db.execute(
        select(SubmissionVersion, Submission, Assignment)
        .join(Submission, Submission.id == SubmissionVersion.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .where(SubmissionVersion.id == version_id)
    ).first()
    if not row: raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    version, submission_item, assignment = row
    if assignment.submitter_type != "INDIVIDUAL" or assignment.status not in {"PUBLISHED", "CLOSED"}:
        raise ApiError(404, "SUBMISSION_VERSION_NOT_FOUND", "提交版本不存在")
    require_class(db, user, assignment.class_id)
    require_peer_review_submission(db, assignment.id, user.id)
    if submission_item.owner_user_id == user.id: raise ApiError(422, "SELF_REVIEW_FORBIDDEN", "不能评价自己的作业")
    reviewer_team = membership(db, assignment.class_id, user.id)
    reviewee_team = membership(db, assignment.class_id, submission_item.owner_user_id)
    if not reviewer_team or not reviewee_team or reviewer_team[1].id != reviewee_team[1].id:
        raise ApiError(403, "TEAM_REVIEW_ONLY", "只能评价本组成员的作业")
    if submission_item.status != "SUBMITTED" or submission_item.current_version_no != version.version_no:
        raise ApiError(409, "SUBMISSION_VERSION_READ_ONLY", "只能评价最新正式提交版本")
    return version, submission_item, assignment


def save_submission_feedback(version_id: UUID, data: SubmissionFeedbackIn, user: User, db: Session, publish: bool) -> dict:
    teacher(user)
    version, submission_item, assignment = feedback_context(db, version_id, user)
    require_writable_class(db, user, assignment.class_id)
    subject_user_id = submission_item.owner_user_id or version.submitted_by
    if submission_item.current_version_no != version.version_no: raise ApiError(409, "SUBMISSION_VERSION_READ_ONLY", "历史提交版本只能查看")
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER").with_for_update())
    current_revision = item.version if item else 0
    if data.revision != current_revision: raise ApiError(409, "FEEDBACK_VERSION_CONFLICT", "反馈已在其他页面更新，请刷新后重试")
    annotations = validate_feedback_annotations(db, version.id, data.annotations)
    payload = {"grade": data.grade, "comment": clean_html(data.comment), "annotations": annotations}
    if not item:
        item = SubmissionAssessment(assignment_id=assignment.id, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=subject_user_id, kind="TEACHER", grade=data.grade, comment=payload["comment"], status="PUBLISHED" if publish else "DRAFT", published_at=now() if publish else None)
        db.add(item); db.flush()
        replace_feedback_annotations(db, item, annotations, user)
    elif publish:
        item.grade, item.comment, item.status, item.published_at, item.draft_payload = data.grade, payload["comment"], "PUBLISHED", now(), None
        item.version += 1
        replace_feedback_annotations(db, item, annotations, user)
    elif item.status == "PUBLISHED":
        item.draft_payload = payload
        item.version += 1
    else:
        item.grade, item.comment = data.grade, payload["comment"]
        item.version += 1
        replace_feedback_annotations(db, item, annotations, user)
    action = "TEACHER_FEEDBACK_PUBLISHED" if publish else "TEACHER_FEEDBACK_DRAFT_SAVED"
    audit(db, user, action, "submission_assessment", str(item.id), {"submission_version_id": str(version.id), "annotation_count": len(annotations)})
    db.commit(); db.refresh(item)
    return {**feedback_json(db, item, True), "result": submission_grade_result(db, version)}


def require_file_access(db: Session, user: User, fid: UUID) -> FileObject:
    f = db.get(FileObject, fid); a = db.get(Assignment, f.assignment_id) if f else None
    if not f or not a: raise ApiError(404, "FILE_NOT_FOUND", "文件不存在")
    require_class(db, user, a.class_id); allowed = user.role == "TEACHER" or f.owner_id == user.id
    if user.role == "STUDENT":
        own_membership = membership(db, a.class_id, user.id)
        mine = own_membership[1] if own_membership else None
        if f.purpose == "ATTACHMENT": allowed = True
        if f.purpose == "REVIEW_CRITERIA" or (f.purpose == "ATTACHMENT" and f.material_type == "CRITERIA"):
            submission, _ = own_submission(db, a, user)
            allowed = bool(submission and submission.status == "SUBMITTED")
        elif f.team_id: allowed = bool(mine and f.team_id == mine.id)
        elif not allowed:
            frozen = db.scalar(select(ReviewAssignment.id).join(ReviewCampaign, ReviewCampaign.id == ReviewAssignment.campaign_id).join(VersionFile, VersionFile.version_id == ReviewAssignment.submission_version_id).where(ReviewCampaign.assignment_id == a.id, ReviewAssignment.reviewer_id == user.id, VersionFile.file_id == f.id, ReviewAssignment.status.in_(["PENDING", "COMPLETED"])).limit(1))
            if frozen:
                allowed = True
            else:
                owner = membership(db, a.class_id, f.owner_id)
                linked = db.execute(select(SubmissionVersion, Submission).join(Submission, Submission.id == SubmissionVersion.submission_id).join(VersionFile, VersionFile.version_id == SubmissionVersion.id).where(VersionFile.file_id == f.id, Submission.status == "SUBMITTED", Submission.current_version_no == SubmissionVersion.version_no)).first()
                reviewer_submitted = latest_personal_submission(db, a.id, user.id)
                allowed = bool(owner and mine and owner[1].id == mine.id and linked and reviewer_submitted)
    if not allowed: raise ApiError(403, "FILE_FORBIDDEN", "无权访问该文件")
    return f


def require_markdown_asset_access(db: Session, user: User, asset_id: UUID) -> MarkdownAsset:
    asset = db.get(MarkdownAsset, asset_id)
    if not asset:
        raise ApiError(404, "MARKDOWN_ASSET_NOT_FOUND", "图片不存在")
    assignment = db.get(Assignment, asset.assignment_id)
    if not assignment:
        raise ApiError(404, "MARKDOWN_ASSET_NOT_FOUND", "图片不存在")
    require_class(db, user, assignment.class_id)
    if asset.workspace_id:
        workspace = db.get(SubmissionWorkspace, asset.workspace_id)
        if workspace and workspace.owner_user_id == user.id:
            return asset
        if workspace and workspace.owner_team_id and db.scalar(select(TeamMember.id).where(TeamMember.team_id == workspace.owner_team_id, TeamMember.user_id == user.id, TeamMember.status == "ACTIVE").limit(1)):
            return asset
    file_ids = list(db.scalars(select(FileObjectAsset.file_id).where(FileObjectAsset.asset_id == asset.id)).all())
    for file_id in file_ids:
        try:
            require_file_access(db, user, file_id)
            return asset
        except ApiError as error:
            if error.status not in {403, 404}:
                raise
    raise ApiError(403, "MARKDOWN_ASSET_FORBIDDEN", "无权访问该图片")
