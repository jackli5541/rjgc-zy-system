from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter
from sqlalchemy import select

from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.html import clean_html
from app.core.utils import now
from app.models import Assignment, AiGradingDraft, AiGradingJob, BackgroundJob, Submission, SubmissionAssessment, SubmissionVersion
from app.modules.ai_grading.schemas import AiGradingAcceptIn, AiGradingJobIn
from app.modules.ai_grading.service import draft_json, draft_state, job_json, require_criteria, successful_baseline

router = APIRouter()


def assignment_for_teacher(db, user, aid):
    teacher(user)
    assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id):
        raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    return assignment


def version_for_assignment(db, aid, version_id):
    row = db.execute(select(SubmissionVersion, Submission).join(Submission, Submission.id == SubmissionVersion.submission_id).where(
        SubmissionVersion.id == version_id, Submission.assignment_id == aid, Submission.status == "SUBMITTED",
        SubmissionVersion.version_no == Submission.current_version_no,
    )).first()
    if not row:
        raise ApiError(409, "SUBMISSION_VERSION_INVALID", "提交版本不存在或已不是当前正式提交")
    version, submission = row
    if db.scalar(select(SubmissionAssessment.id).where(
        SubmissionAssessment.submission_version_id == version.id,
        SubmissionAssessment.evaluator_id.is_not(None),
        SubmissionAssessment.kind == "TEACHER",
        SubmissionAssessment.status == "PUBLISHED",
    ).limit(1)):
        raise ApiError(409, "SUBMISSION_ALREADY_GRADED", "该提交已经完成教师评分")
    return version, submission


@router.post("/api/v1/assignments/{aid}/ai-grading/jobs", status_code=202)
def create_job(aid: UUID, data: AiGradingJobIn, user: CsrfUser, db: Db):
    assignment = assignment_for_teacher(db, user, aid)
    require_criteria(db, assignment)
    ids = list(dict.fromkeys(data.submission_version_ids))
    versions = []
    for version_id in ids:
        version, _ = version_for_assignment(db, aid, version_id)
        versions.append(version)
    job = AiGradingJob(id=uuid4(), assignment_id=aid, teacher_id=user.id, status="PENDING", total_count=len(versions))
    db.add(job)
    for version in versions:
        current = db.scalar(select(AiGradingDraft).where(
            AiGradingDraft.submission_version_id == version.id,
            AiGradingDraft.teacher_id == user.id,
            AiGradingDraft.status.in_(["PROCESSING", "READY"]),
        ).order_by(AiGradingDraft.created_at.desc()))
        if current:
            continue
        db.add(AiGradingDraft(job_id=job.id, assignment_id=aid, submission_version_id=version.id, teacher_id=user.id, assignment_version=assignment.version, status="PROCESSING", rubric_snapshot={}))
    db.add(BackgroundJob(kind="AI_GRADING", status="AI_PENDING", payload={"job_id": str(job.id)}, available_at=now()))
    audit(db, user, "AI_GRADING_JOB_CREATED", "ai_grading_job", str(job.id), {"count": len(versions)})
    db.commit()
    return job_json(db, job)


@router.get("/api/v1/assignments/{aid}/ai-grading/jobs/{job_id}")
def get_job(aid: UUID, job_id: UUID, user: CurrentUser, db: Db):
    assignment_for_teacher(db, user, aid)
    job = db.scalar(select(AiGradingJob).where(AiGradingJob.id == job_id, AiGradingJob.assignment_id == aid, AiGradingJob.teacher_id == user.id))
    if not job:
        raise ApiError(404, "AI_GRADING_JOB_NOT_FOUND", "批改任务不存在")
    return job_json(db, job)


@router.get("/api/v1/assignments/{aid}/submissions/{version_id}/ai-grading-draft")
def get_draft(aid: UUID, version_id: UUID, user: CurrentUser, db: Db):
    assignment_for_teacher(db, user, aid)
    item = db.scalar(select(AiGradingDraft).where(
        AiGradingDraft.assignment_id == aid,
        AiGradingDraft.submission_version_id == version_id,
        AiGradingDraft.teacher_id == user.id,
    ).order_by(AiGradingDraft.created_at.desc()))
    return {"draft": draft_state(db, item)}


@router.post("/api/v1/assignments/{aid}/submissions/{version_id}/ai-grading-draft/retry", status_code=202)
def retry_draft(aid: UUID, version_id: UUID, user: CsrfUser, db: Db):
    assignment = assignment_for_teacher(db, user, aid)
    version, _ = version_for_assignment(db, aid, version_id)
    # Serialize initial creation as well as retries for the same submission.
    db.scalar(select(SubmissionVersion).where(SubmissionVersion.id == version.id).with_for_update())
    item = db.scalar(select(AiGradingDraft).where(AiGradingDraft.assignment_id == aid, AiGradingDraft.submission_version_id == version.id, AiGradingDraft.teacher_id == user.id).order_by(AiGradingDraft.created_at.desc()))
    current = draft_state(db, item)
    if current and current["status"] == "PROCESSING":
        return current
    require_criteria(db, assignment)
    if not item:
        item = AiGradingDraft(assignment_id=aid, submission_version_id=version.id, teacher_id=user.id, assignment_version=assignment.version, rubric_snapshot={})
        db.add(item)
        db.flush()
    previous = successful_baseline(item)
    item.status, item.error_message, item.assignment_version = "PROCESSING", None, assignment.version
    job_id, run_id, queued_at = uuid4(), str(uuid4()), now()
    item.rubric_snapshot = {"_previous": previous, "_run": {"id": run_id, "job_id": str(job_id), "queued_at": queued_at.isoformat(), "phase": "QUEUED"}}
    item.analysis, item.suggested_grade, item.suggested_comment = None, None, None
    item.updated_at = queued_at
    db.add(BackgroundJob(id=job_id, kind="AI_GRADING_DRAFT", status="AI_PENDING", payload={"draft_id": str(item.id), "run_id": run_id}, available_at=queued_at))
    db.commit()
    return draft_json(item)


@router.post("/api/v1/assignments/{aid}/submissions/{version_id}/ai-grading-draft/accept")
def accept_draft(aid: UUID, version_id: UUID, data: AiGradingAcceptIn, user: CsrfUser, db: Db):
    assignment = assignment_for_teacher(db, user, aid)
    version, submission = version_for_assignment(db, aid, version_id)
    item = db.scalar(select(AiGradingDraft).where(AiGradingDraft.assignment_id == aid, AiGradingDraft.submission_version_id == version.id, AiGradingDraft.teacher_id == user.id, AiGradingDraft.status == "READY").order_by(AiGradingDraft.created_at.desc()))
    if not item or item.assignment_version != assignment.version:
        raise ApiError(409, "AI_GRADING_DRAFT_STALE", "批改草稿已过期，请重新生成")
    assessment = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    if assessment:
        assessment.grade, assessment.comment, assessment.status, assessment.published_at = data.grade, clean_html(data.comment), "PUBLISHED", now()
        assessment.version += 1
    else:
        assessment = SubmissionAssessment(assignment_id=aid, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=submission.owner_user_id or version.submitted_by, kind="TEACHER", grade=data.grade, comment=clean_html(data.comment), status="PUBLISHED", published_at=now())
        db.add(assessment)
    item.status = "ACCEPTED"
    audit(db, user, "AI_GRADING_DRAFT_ACCEPTED", "ai_grading_draft", str(item.id), {"grade": data.grade})
    db.commit()
    return {"accepted": True, "grade": data.grade, "comment": data.comment}
