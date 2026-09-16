import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, select

from app.database import SessionLocal
from app.grading import finalize_campaign
from app.models import Assignment, AuditLog, BackgroundJob, ClassMember, FileObject, ImportBatch, LoginSession, Notification, ReviewAssignment, ReviewCampaign, Submission, SubmissionVersion, TeachingClass, Team, TeamMember, User
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


def process_auto_review(db, current: datetime) -> None:
    assignment = db.scalar(
        select(Assignment)
        .where(Assignment.auto_review_enabled.is_(True), Assignment.auto_review_status == "PENDING", Assignment.status.in_(["PUBLISHED", "CLOSED"]), Assignment.due_at <= current)
        .order_by(Assignment.due_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not assignment:
        return
    existing = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment.id))
    if existing:
        assignment.auto_review_status = "CREATED"
        return
    if not assignment.auto_review_due_at or assignment.auto_review_due_at <= current:
        assignment.auto_review_status, assignment.auto_review_error = "FAILED", "互评截止时间已过，未自动创建"
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
    if assignment.auto_review_mode == "CLASS":
        groups = [("教学班", frozen_rows)]
    else:
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
    db.add(AuditLog(actor_id=course.teacher_id if course else None, action="REVIEW_CAMPAIGN_AUTO_CREATED", object_type="review_campaign", object_id=str(campaign.id), changes={"assignment_id": str(assignment.id), "mode": assignment.auto_review_mode}))


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
    db.add(AuditLog(actor_id=course.teacher_id if course else None, action="PEER_GRADES_GENERATED", object_type="review_campaign", object_id=str(campaign.id), changes={"assignment_id": str(campaign.assignment_id)}))


def run_once() -> None:
    with SessionLocal.begin() as db:
        current = datetime.now(UTC)
        db.execute(delete(LoginSession).where(LoginSession.expires_at < current))
        db.execute(delete(ImportBatch).where(ImportBatch.status == "PREVIEWED", ImportBatch.created_at < current - timedelta(days=1)))
        process_auto_review(db, current)
        process_due_campaign(db, current)
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.status == "PENDING", BackgroundJob.available_at <= current).with_for_update(skip_locked=True).limit(1))
        if not job:
            return
        job.status = "RUNNING"
        job.locked_at = current
        job.attempts += 1
        job_id = job.id
        job_kind = job.kind
        try:
            file_id = UUID(job.payload["file_id"]) if job_kind == "FILE_PREVIEW" and job.payload.get("file_id") else None
        except (KeyError, TypeError, ValueError):
            file_id = None

    if job_kind == "FILE_PREVIEW" and file_id:
        process_preview(job_id, file_id)
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
