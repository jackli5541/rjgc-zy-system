import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
from uuid import UUID

from sqlalchemy import and_, delete, or_, select

from app.database import SessionLocal
from app.grading import finalize_campaign
from app import storage
from app.models import Assignment, AuditLog, BackgroundJob, ClassMember, FileObject, FileObjectAsset, ImportBatch, LoginSession, MarkdownAsset, Notification, RealtimeEvent, ReviewAssignment, ReviewCampaign, Submission, SubmissionDocumentAsset, SubmissionVersion, TeachingClass, Team, TeamMember, User
from app.realtime import publish_event
from app.settings import settings


def fail_preview(job_id: UUID, file_id: UUID | None, reason: str) -> None:
    with SessionLocal.begin() as db:
        job = db.get(BackgroundJob, job_id)
        if job:
            job.status = "FAILED"
            job.last_error = reason[:500]
        if file_id:
            file = db.get(FileObject, file_id)
            if file:
                file.preview_status = "FAILED"
                file.preview_error = reason[:500]


def process_preview(job_id: UUID, file_id: UUID) -> None:
    fail_preview(job_id, file_id, "Office 文件本期仅支持权限校验后的原文件下载")


def process_oss_delete(job_id: UUID, keys: list[str]) -> None:
    failed_keys = []
    errors = []
    for key in keys:
        try:
            storage.delete_object(key)
        except Exception as error:
            failed_keys.append(key)
            errors.append(f"{key}: {type(error).__name__}")
    with SessionLocal.begin() as db:
        job = db.get(BackgroundJob, job_id)
        if not job:
            return
        job.payload = {"keys": failed_keys}
        if failed_keys:
            job.status = "PENDING"
            job.available_at = datetime.now(UTC) + timedelta(minutes=min(60, 2 ** min(job.attempts, 5)))
            job.locked_at = None
            job.last_error = "; ".join(errors)[:500]
        else:
            job.status = "COMPLETED"
            job.last_error = None


def process_archive_export(job_id: UUID, payload: dict) -> None:
    from app.archive_exports import build_assignment_archive, build_materials_archive, build_portfolio_archive, build_team_archive, build_workspace_document_archive

    target = None
    requested_filename = Path(str(payload.get("filename", ""))).name
    filename = requested_filename if requested_filename.lower().endswith(".zip") else "archive.zip"
    result_path = f"exports/{job_id}/{filename}"
    try:
        with SessionLocal() as db:
            kind = payload.get("archive_kind")
            if kind == "ASSIGNMENT":
                target = build_assignment_archive(db, UUID(payload["assignment_id"]))
            elif kind == "TEAM":
                target = build_team_archive(db, UUID(payload["team_id"]))
            elif kind == "MATERIALS":
                target = build_materials_archive(db, [UUID(item) for item in payload.get("file_ids", [])])
            elif kind == "WORKSPACE_DOCUMENT":
                target = build_workspace_document_archive(db, UUID(payload["document_id"]))
            elif kind == "PORTFOLIO":
                student_id = UUID(payload["student_id"]) if payload.get("student_id") else None
                target = build_portfolio_archive(db, UUID(payload["class_id"]), student_id)
            else:
                raise ValueError("未知的归档类型")
        storage.put_object(result_path, target)
        with SessionLocal.begin() as db:
            job = db.get(BackgroundJob, job_id)
            if job:
                job.status = "COMPLETED"
                job.result_path = result_path
                job.last_error = None
    except Exception as error:
        with SessionLocal.begin() as db:
            job = db.get(BackgroundJob, job_id)
            if job:
                job.status = "FAILED"
                job.last_error = str(error)[:500]
        try:
            storage.delete_object(result_path)
        except Exception:
            pass
    finally:
        if target:
            target.unlink(missing_ok=True)


def process_auto_review(db, current: datetime) -> None:
    assignment = db.scalar(
        select(Assignment)
        .where(Assignment.auto_review_enabled == True, Assignment.auto_review_status == "PENDING", Assignment.status.in_(["PUBLISHED", "CLOSED"]), Assignment.due_at <= current)  # noqa: E712
        .order_by(Assignment.due_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not assignment:
        return
    existing = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment.id))
    if existing:
        assignment.auto_review_status = "CREATED"
        publish_event(db, class_id=assignment.class_id, scopes=["assignments", "reviews"], resource_type="assignment", resource_id=assignment.id)
        return
    if not assignment.auto_review_due_at or assignment.auto_review_due_at <= current:
        assignment.auto_review_status, assignment.auto_review_error = "FAILED", "互评截止时间已过，未自动创建"
        publish_event(db, class_id=assignment.class_id, scopes=["assignments", "reviews"], resource_type="assignment", resource_id=assignment.id)
        return
    frozen_rows = db.execute(
        select(User, SubmissionVersion)
        .join(ClassMember, and_(ClassMember.user_id == User.id, ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT"))
        .join(Submission, and_(Submission.owner_user_id == User.id, Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED"))
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(User.status == "ACTIVE")
        .order_by(User.login_name)
        .with_for_update()
    ).all()
    if len(frozen_rows) < 2:
        assignment.auto_review_status, assignment.auto_review_error = "FAILED", "全班已正式提交学生少于 2 人"
        publish_event(db, class_id=assignment.class_id, scopes=["assignments", "reviews"], resource_type="assignment", resource_id=assignment.id)
        return

    campaign = ReviewCampaign(assignment_id=assignment.id, class_id=assignment.class_id, mode=assignment.auto_review_mode, criteria_text=(assignment.auto_review_criteria_text or "").strip(), assignment_snapshot_at=current, rubric=[{"key": "score", "label": "总分", "weight": 100}], comment_min_length=1, due_at=assignment.auto_review_due_at, publish_at=current, require_all=False, allow_update=True)
    db.add(campaign)
    db.flush()
    team_by_user = {
        user_id: team_id
        for user_id, team_id in db.execute(
            select(TeamMember.user_id, TeamMember.team_id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.class_id == assignment.class_id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")
        ).all()
    }
    grouped = {(team.id, team.name): [] for team in db.scalars(select(Team).where(Team.class_id == assignment.class_id, Team.status == "ACTIVE")).all()}
    for person, version in frozen_rows:
        team_row = db.execute(select(TeamMember.team_id, Team.name).join(Team, Team.id == TeamMember.team_id).where(TeamMember.class_id == assignment.class_id, TeamMember.user_id == person.id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")).first()
        key, label = (team_row.team_id, team_row.name) if team_row else (None, "未分组")
        grouped.setdefault((key, label), []).append((person, version))
    groups = [(label, rows) for (_, label), rows in grouped.items()]
    for label, rows in groups:
        if len(rows) < 2:
            reason = f"{label} 已正式提交人数少于 2 人"
            for person, _ in rows:
                db.add(ReviewAssignment(campaign_id=campaign.id, reviewer_id=person.id, participant_team_id=team_by_user.get(person.id), status="SKIPPED", skip_reason=reason))
            continue
        for index, (reviewer, _) in enumerate(rows):
            reviewee, version = rows[(index + 1) % len(rows)]
            db.add(ReviewAssignment(campaign_id=campaign.id, reviewer_id=reviewer.id, participant_team_id=team_by_user.get(reviewer.id), reviewee_id=reviewee.id, submission_version_id=version.id))
            db.add(Notification(user_id=reviewer.id, kind="REVIEW_ASSIGNED", title=f"新的互评任务：{assignment.title}", object_type="review_campaign", object_id=str(campaign.id)))
    course = db.get(TeachingClass, assignment.class_id)
    assignment.auto_review_status, assignment.auto_review_error = "CREATED", None
    db.add(AuditLog(actor_id=course.teacher_id if course else None, class_id=course.id if course else None, class_semester=course.semester if course else None, class_name=course.name if course else None, action="REVIEW_CAMPAIGN_AUTO_CREATED", object_type="review_campaign", object_id=str(campaign.id), changes={"assignment_id": str(assignment.id), "mode": assignment.auto_review_mode}))
    publish_event(db, class_id=assignment.class_id, scopes=["assignments", "reviews", "notifications", "dashboard"], resource_type="review_campaign", resource_id=campaign.id)


def process_due_campaign(db, current: datetime) -> None:
    campaign = db.scalar(
        select(ReviewCampaign)
        .where(ReviewCampaign.status.in_(["ACTIVE", "CLOSED"]), ReviewCampaign.due_at <= current, ReviewCampaign.assignment_snapshot_at.is_not(None), ReviewCampaign.grades_generated_at.is_(None))
        .order_by(ReviewCampaign.due_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not campaign:
        return
    finalize_campaign(db, campaign, current)
    course = db.get(TeachingClass, campaign.class_id)
    db.add(AuditLog(actor_id=course.teacher_id if course else None, class_id=course.id if course else None, class_semester=course.semester if course else None, class_name=course.name if course else None, action="PEER_GRADES_GENERATED", object_type="review_campaign", object_id=str(campaign.id), changes={"assignment_id": str(campaign.assignment_id)}))
    publish_event(db, class_id=campaign.class_id, scopes=["reviews", "grades", "dashboard"], resource_type="review_campaign", resource_id=campaign.id)


def cleanup_markdown_assets(db, current: datetime) -> None:
    cutoff = current - timedelta(hours=settings.markdown_asset_orphan_hours)
    assets = db.scalars(
        select(MarkdownAsset)
        .where(MarkdownAsset.orphaned_at.is_not(None), MarkdownAsset.orphaned_at <= cutoff)
        .order_by(MarkdownAsset.orphaned_at)
        .with_for_update(skip_locked=True)
        .limit(20)
    ).all()
    for asset in assets:
        has_document = db.scalar(select(SubmissionDocumentAsset.asset_id).where(SubmissionDocumentAsset.asset_id == asset.id).limit(1))
        has_file = db.scalar(select(FileObjectAsset.asset_id).where(FileObjectAsset.asset_id == asset.id).limit(1))
        if has_document or has_file:
            asset.orphaned_at = None
            continue
        storage.delete_object(asset.storage_path)
        db.delete(asset)


def cleanup_archive_exports(db, current: datetime) -> None:
    jobs = db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "ARCHIVE_EXPORT",
            BackgroundJob.status.in_(["COMPLETED", "FAILED"]),
            BackgroundJob.available_at < current - timedelta(hours=settings.export_archive_hours),
        )
        .order_by(BackgroundJob.available_at)
        .with_for_update(skip_locked=True)
        .limit(20)
    ).all()
    for job in jobs:
        if job.result_path:
            storage.delete_object(job.result_path)
        db.delete(job)


def run_once() -> None:
    with SessionLocal.begin() as db:
        current = datetime.now(UTC)
        db.execute(delete(LoginSession).where(LoginSession.expires_at < current))
        db.execute(delete(ImportBatch).where(ImportBatch.status == "PREVIEWED", ImportBatch.created_at < current - timedelta(days=1)))
        db.execute(delete(RealtimeEvent).where(RealtimeEvent.created_at < current - timedelta(days=1)))
        process_auto_review(db, current)
        process_due_campaign(db, current)
        cleanup_markdown_assets(db, current)
        cleanup_archive_exports(db, current)
        # Old immediate archive jobs used SQL Server's local CURRENT_TIMESTAMP,
        # which could be stored eight hours ahead while this worker compares UTC.
        legacy_archive_cutoff = current + timedelta(hours=9)
        job = db.scalar(
            select(BackgroundJob)
            .where(
                or_(
                    and_(BackgroundJob.status == "ARCHIVE_PENDING", BackgroundJob.available_at <= current),
                    and_(BackgroundJob.status == "PENDING", BackgroundJob.available_at <= current),
                    and_(
                        BackgroundJob.status == "PENDING",
                        BackgroundJob.kind == "ARCHIVE_EXPORT",
                        BackgroundJob.attempts == 0,
                        BackgroundJob.available_at <= legacy_archive_cutoff,
                    ),
                ),
            )
            .order_by(BackgroundJob.available_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return
        job.status = "RUNNING"
        job.locked_at = current
        job.attempts += 1
        job_id = job.id
        job_kind = job.kind
        job_payload = job.payload or {}
        try:
            file_id = UUID(job_payload["file_id"]) if job_kind == "FILE_PREVIEW" and job_payload.get("file_id") else None
        except (KeyError, TypeError, ValueError):
            file_id = None
        delete_keys = [key for key in job_payload.get("keys", []) if isinstance(key, str)] if job_kind == "OSS_DELETE" else []

    print(f"worker claimed job id={job_id} kind={job_kind!r}", flush=True)
    if job_kind == "FILE_PREVIEW" and file_id:
        process_preview(job_id, file_id)
    elif job_kind == "ARCHIVE_EXPORT":
        process_archive_export(job_id, job_payload)
    elif job_kind == "OSS_DELETE":
        process_oss_delete(job_id, delete_keys)
    else:
        fail_preview(job_id, file_id, "当前任务类型没有可用处理器")


def main() -> None:
    while True:
        try:
            run_once()
        except Exception as error:
            print(f"worker cycle failed: {type(error).__name__}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
