from __future__ import annotations

from datetime import timedelta
from fastapi import APIRouter, Query, Response
from sqlalchemy import and_, delete, func, or_, select
from uuid import UUID

from app import storage
from app.database import SessionLocal
from app.models import Assignment, BackgroundJob, ClassMember, FileObject, FileObjectAsset, Grade, GradeCoefficient, GradeRevision, MarkdownAsset, PeerReview, ReviewAssignment, ReviewCampaign, Submission, SubmissionAnnotation, SubmissionAssessment, SubmissionDocument, SubmissionDocumentAsset, SubmissionVersion, SubmissionWorkspace, VersionFile
from app.realtime import publish_event
from app.core.audit import audit, notify, realtime_scopes
from app.core.context import request_client_id
from app.core.deps import CsrfUser, CurrentUser, Db, require_class, require_team, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.html import clean_html
from app.core.utils import now
from app.modules.assignments.schemas import AssignmentBulkIn, AssignmentIn, AssignmentUpdateIn
from app.modules.assignments.service import assignment_json, assignment_progress_json, assignment_review_campaign, create_assignments_for_classes, has_review_criteria_file, writable_teacher_classes

router = APIRouter()

@router.get("/api/v1/assignments")
def assignments(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    team = require_team(db, class_id, user)[1] if user.role == "STUDENT" else None
    q = select(Assignment).where(Assignment.class_id == class_id)
    if user.role == "STUDENT":
        q = q.where(
            Assignment.status.in_(["PUBLISHED", "CLOSED"]),
            or_(Assignment.starts_at.is_(None), Assignment.starts_at <= now()),
        )
    items = db.scalars(q.order_by(Assignment.created_at.desc())).all()
    submissions_by_assignment = {}
    pending_teacher_reviews = {}
    if user.role == "STUDENT" and items:
        assignment_ids = [item.id for item in items]
        ownership = or_(Submission.owner_user_id == user.id, Submission.owner_team_id == team.id)
        submissions_by_assignment = {
            submission.assignment_id: submission
            for submission in db.scalars(
                select(Submission).where(Submission.assignment_id.in_(assignment_ids), ownership)
            ).all()
        }
    elif user.role == "TEACHER" and items:
        assignment_ids = [item.id for item in items]
        pending_teacher_reviews = dict(db.execute(
            select(Submission.assignment_id, func.count(SubmissionVersion.id))
            .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
            .where(
                Submission.assignment_id.in_(assignment_ids),
                Submission.status == "SUBMITTED",
                ~select(SubmissionAssessment.id).where(
                    SubmissionAssessment.submission_version_id == SubmissionVersion.id,
                    SubmissionAssessment.kind == "TEACHER",
                    SubmissionAssessment.status == "PUBLISHED",
                ).exists(),
            )
            .group_by(Submission.assignment_id)
        ).all())
    result = []
    for item in items:
        payload = assignment_json(item)
        if user.role == "STUDENT":
            submission = submissions_by_assignment.get(item.id)
            payload["submission_status"] = submission.status if submission else "NOT_SUBMITTED"
        else:
            payload["progress"] = assignment_progress_json(db, item)
            payload["pending_teacher_review_count"] = pending_teacher_reviews.get(item.id, 0)
        result.append(payload)
    return {"items": result, "total": len(result)}


@router.post("/api/v1/assignments", status_code=201)
def create_assignment(data: AssignmentIn, user: CsrfUser, db: Db):
    courses = writable_teacher_classes(db, user, [data.class_id])
    item = create_assignments_for_classes(data, courses, user, db)[0]
    db.commit(); return assignment_json(item)


@router.post("/api/v1/assignments/bulk", status_code=201)
def create_assignments_bulk(data: AssignmentBulkIn, user: CsrfUser, db: Db):
    courses = writable_teacher_classes(db, user, data.class_ids)
    items = create_assignments_for_classes(data, courses, user, db)
    db.commit(); return {"items": [assignment_json(x) for x in items], "total": len(items)}


@router.patch("/api/v1/assignments/{aid}")
def update_assignment(aid: UUID, data: AssignmentUpdateIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.version != data.version: raise ApiError(409, "ASSIGNMENT_VERSION_CONFLICT", "作业已被修改，请刷新后重试", {"current_version": assignment.version})
    has_submissions = bool(db.scalar(select(Submission.id).where(Submission.assignment_id == aid).limit(1)))
    if data.submitter_type and data.submitter_type != assignment.submitter_type and has_submissions: raise ApiError(409, "SUBMITTER_TYPE_LOCKED", "已有提交后不能修改提交类型")
    starts_at = data.starts_at if data.starts_at is not None else assignment.starts_at
    due_at = data.due_at if data.due_at is not None else assignment.due_at
    if starts_at and starts_at >= due_at: raise ApiError(422, "ASSIGNMENT_TIME_INVALID", "开始时间必须早于截止时间")

    review_fields = {"auto_review_enabled", "auto_review_mode", "auto_review_criteria_text", "auto_review_due_at"}
    changing_review_config = bool(review_fields & data.model_fields_set)
    campaign = assignment_review_campaign(db, aid)
    previous_class_id = assignment.class_id
    changing_class = data.class_id is not None and data.class_id != previous_class_id
    if changing_class:
        writable_teacher_classes(db, user, [data.class_id])
        if has_submissions or campaign:
            raise ApiError(409, "ASSIGNMENT_CLASS_LOCKED", "已有提交记录或互评活动，不能修改教学班")
    if changing_review_config and (assignment.status == "CLOSED" or assignment.due_at <= now() or campaign):
        raise ApiError(409, "AUTO_REVIEW_CONFIG_LOCKED", "作业已截止或互评活动已创建，不能修改互评配置")

    auto_review_enabled = data.auto_review_enabled if "auto_review_enabled" in data.model_fields_set else assignment.auto_review_enabled
    auto_review_mode = data.auto_review_mode if "auto_review_mode" in data.model_fields_set else assignment.auto_review_mode
    auto_review_criteria_text = data.auto_review_criteria_text if "auto_review_criteria_text" in data.model_fields_set else assignment.auto_review_criteria_text
    auto_review_due_at = data.auto_review_due_at if "auto_review_due_at" in data.model_fields_set else assignment.auto_review_due_at
    submitter_type = data.submitter_type or assignment.submitter_type
    if assignment.status == "PUBLISHED" and submitter_type == "TEAM" and due_at <= now():
        raise ApiError(422, "TEAM_ASSIGNMENT_DUE_INVALID", "小组作业截止时间必须晚于当前时间")
    if auto_review_enabled and campaign is None:
        if submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "自动互评只能关联个人作业")
        if not auto_review_mode or not auto_review_due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_REQUIRED", "请完整配置自动互评模式和截止时间")
        if auto_review_due_at <= due_at: raise ApiError(422, "AUTO_REVIEW_TIME_INVALID", "互评截止时间必须晚于作业截止时间")
        if not (auto_review_criteria_text or "").strip() and not has_review_criteria_file(db, aid):
            raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "互评标准文字和附件至少提供一种")
    for key in ("title", "description", "starts_at", "due_at", "allow_late", "submitter_type", "kind"):
        value = getattr(data, key)
        if value is not None:
            if key == "description": value = clean_html(value)
            setattr(assignment, key, value.strip() if isinstance(value, str) else value)
    if changing_review_config:
        assignment.auto_review_enabled = bool(auto_review_enabled)
        assignment.auto_review_mode = auto_review_mode if auto_review_enabled else None
        assignment.auto_review_criteria_text = (auto_review_criteria_text or "").strip() if auto_review_enabled else None
        assignment.auto_review_due_at = auto_review_due_at if auto_review_enabled else None
        assignment.auto_review_status = "PENDING" if auto_review_enabled else None
        assignment.auto_review_error = None
    if changing_class:
        assignment.class_id = data.class_id
        publish_event(db, class_id=previous_class_id, scopes=realtime_scopes("ASSIGNMENT_UPDATED"), resource_type="assignment", resource_id=str(aid), source_client_id=request_client_id.get())
        if assignment.status == "PUBLISHED":
            for member in db.scalars(select(ClassMember).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE")):
                notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"新作业：{assignment.title}")
    changes = {"previous_class_id": str(previous_class_id), "class_id": str(assignment.class_id)} if changing_class else None
    assignment.version += 1; audit(db, user, "ASSIGNMENT_UPDATED", "assignment", str(aid), changes); db.commit(); return assignment_json(assignment)


@router.post("/api/v1/assignments/{aid}/publish")
def publish_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    republishing = assignment.status in {"PUBLISHED", "CLOSED"}
    if assignment.status == "CLOSED" and assignment.due_at <= now():
        raise ApiError(422, "ASSIGNMENT_DUE_INVALID", "重新发布已截止作业前，请将截止时间设置为未来时间")
    if assignment.submitter_type == "TEAM" and assignment.due_at <= now():
        raise ApiError(422, "TEAM_ASSIGNMENT_DUE_INVALID", "小组作业截止时间必须晚于当前时间")
    if assignment.auto_review_enabled:
        criteria_exists = bool(db.scalar(select(FileObject.id).where(FileObject.assignment_id == aid, FileObject.purpose == "REVIEW_CRITERIA").limit(1)))
        if not (assignment.auto_review_criteria_text or "").strip() and not criteria_exists: raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "自动互评标准文字和附件至少提供一种")
        if assignment.submitter_type != "INDIVIDUAL" or not assignment.auto_review_mode or not assignment.auto_review_due_at or assignment.auto_review_due_at <= assignment.due_at: raise ApiError(422, "AUTO_REVIEW_CONFIG_INVALID", "自动互评配置不完整")
    assignment.status = "PUBLISHED"; assignment.version += 1
    for member in db.scalars(select(ClassMember).where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE")): notify(db, member.user_id, "ASSIGNMENT_PUBLISHED", f"{'作业已更新' if republishing else '新作业'}：{assignment.title}")
    audit(db, user, "ASSIGNMENT_PUBLISHED", "assignment", str(aid)); db.commit(); return assignment_json(assignment)


@router.post("/api/v1/assignments/{aid}/retract")
def retract_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status == "DRAFT": return assignment_json(assignment)
    if assignment.status not in {"PUBLISHED", "CLOSED"}: raise ApiError(409, "ASSIGNMENT_RETRACT_INVALID", "当前作业状态不能撤回发布")
    previous_status = assignment.status
    assignment.status = "DRAFT"
    assignment.version += 1
    audit(db, user, "ASSIGNMENT_RETRACTED", "assignment", str(aid), {"from": previous_status, "to": "DRAFT"})
    db.commit()
    return assignment_json(assignment)


@router.post("/api/v1/assignments/{aid}/close")
def close_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    if assignment.status == "CLOSED": return assignment_json(assignment)
    if assignment.status != "PUBLISHED": raise ApiError(409, "ASSIGNMENT_NOT_PUBLISHED", "只有已发布的作业可以提前截止")
    assignment.status = "CLOSED"
    assignment.due_at = now()
    assignment.version += 1
    audit(db, user, "ASSIGNMENT_CLOSED", "assignment", str(aid), {"due_at": assignment.due_at.isoformat()})
    db.commit()
    return assignment_json(assignment)


@router.delete("/api/v1/assignments/{aid}", status_code=204)
def delete_assignment(aid: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == aid).with_for_update())
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    assignment_files = list(db.scalars(select(FileObject).where(FileObject.assignment_id == aid)).all())
    keys = [item.storage_path for item in assignment_files]
    markdown_assets = list(db.scalars(select(MarkdownAsset).where(MarkdownAsset.assignment_id == aid)).all())
    asset_keys = [item.storage_path for item in markdown_assets]
    cleanup_keys = keys + asset_keys
    cleanup_job = BackgroundJob(kind="OSS_DELETE", payload={"keys": cleanup_keys}, available_at=now() + timedelta(minutes=5)) if cleanup_keys else None
    title = assignment.title
    audit(db, user, "ASSIGNMENT_DELETED", "assignment", str(aid), {"title": title})
    submission_ids = select(Submission.id).where(Submission.assignment_id == aid)
    version_ids = select(SubmissionVersion.id).where(SubmissionVersion.submission_id.in_(submission_ids))
    assessment_ids = select(SubmissionAssessment.id).where(SubmissionAssessment.assignment_id == aid)
    campaign_ids = select(ReviewCampaign.id).where(ReviewCampaign.assignment_id == aid)
    grade_ids = select(Grade.id).where(Grade.assignment_id == aid)
    db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id.in_(assessment_ids)))
    db.execute(delete(GradeRevision).where(GradeRevision.grade_id.in_(grade_ids)))
    db.execute(delete(Grade).where(Grade.assignment_id == aid))
    db.execute(delete(PeerReview).where(PeerReview.campaign_id.in_(campaign_ids)))
    db.execute(delete(ReviewAssignment).where(ReviewAssignment.campaign_id.in_(campaign_ids)))
    db.execute(delete(SubmissionAssessment).where(SubmissionAssessment.assignment_id == aid))
    db.execute(delete(VersionFile).where(VersionFile.version_id.in_(version_ids)))
    db.execute(delete(SubmissionVersion).where(SubmissionVersion.submission_id.in_(submission_ids)))
    db.execute(delete(Submission).where(Submission.assignment_id == aid))
    db.execute(delete(GradeCoefficient).where(GradeCoefficient.assignment_id == aid))
    db.execute(delete(ReviewCampaign).where(ReviewCampaign.assignment_id == aid))
    asset_ids = [item.id for item in markdown_assets]
    file_ids = [item.id for item in assignment_files]
    workspace_ids = select(SubmissionWorkspace.id).where(SubmissionWorkspace.assignment_id == aid)
    document_ids = select(SubmissionDocument.id).where(SubmissionDocument.workspace_id.in_(workspace_ids))
    if asset_ids:
        db.execute(delete(SubmissionDocumentAsset).where(SubmissionDocumentAsset.asset_id.in_(asset_ids)))
        db.execute(delete(FileObjectAsset).where(FileObjectAsset.asset_id.in_(asset_ids)))
    if file_ids:
        db.execute(delete(FileObjectAsset).where(FileObjectAsset.file_id.in_(file_ids)))
    db.execute(delete(SubmissionDocumentAsset).where(SubmissionDocumentAsset.document_id.in_(document_ids)))
    db.execute(delete(MarkdownAsset).where(MarkdownAsset.assignment_id == aid))
    db.execute(delete(FileObject).where(FileObject.assignment_id == aid))
    db.delete(assignment)
    if cleanup_job:
        db.add(cleanup_job)
    db.commit()
    if cleanup_job:
        failed_keys = []
        for key in cleanup_keys:
            try:
                storage.delete_object(key)
            except Exception:
                failed_keys.append(key)
        with SessionLocal.begin() as cleanup_db:
            persisted_job = cleanup_db.get(BackgroundJob, cleanup_job.id)
            if persisted_job:
                persisted_job.payload = {"keys": failed_keys}
                persisted_job.status = "PENDING" if failed_keys else "COMPLETED"
                persisted_job.last_error = "OSS 对象删除失败，等待重试" if failed_keys else None
    return Response(status_code=204)
