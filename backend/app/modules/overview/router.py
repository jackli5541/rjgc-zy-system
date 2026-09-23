from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import and_, func, or_, select
from uuid import UUID

from app.models import Assignment, ClassMember, PeerReview, ReviewAssignment, ReviewCampaign, Submission, SubmissionAssessment, SubmissionVersion, Team, TeamMember, User, VersionFile
from app.core.deps import CurrentUser, Db, require_class, require_team
from app.core.utils import now
from app.modules.members.service import class_json

router = APIRouter()

@router.get("/api/v1/classes/{cid}/dashboard")
def dashboard(cid: UUID, user: CurrentUser, db: Db):
    course = require_class(db, user, cid)
    if user.role == "STUDENT": require_team(db, cid, user)
    members = db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE")) or 0
    teams = db.scalar(select(func.count()).select_from(Team).where(Team.class_id == cid, Team.status == "ACTIVE")) or 0
    ungrouped_members = db.scalar(
        select(func.count()).select_from(ClassMember).where(
            ClassMember.class_id == cid,
            ClassMember.status == "ACTIVE",
            ~select(TeamMember.id).where(
                TeamMember.class_id == cid,
                TeamMember.user_id == ClassMember.user_id,
                TeamMember.status == "ACTIVE",
            ).exists(),
        )
    ) or 0
    visible_assignment = or_(Assignment.starts_at.is_(None), Assignment.starts_at <= now())
    active_filters = [Assignment.class_id == cid, Assignment.status == "PUBLISHED", Assignment.due_at >= now()]
    if user.role == "STUDENT": active_filters.append(visible_assignment)
    active = db.scalar(select(func.count()).select_from(Assignment).where(*active_filters)) or 0
    latest_assignment = db.scalar(select(Assignment).where(*active_filters).order_by(Assignment.created_at.desc()).limit(1))
    assignment_expected = (members if latest_assignment.submitter_type == "INDIVIDUAL" else teams) if latest_assignment else 0
    assignment_submitted = db.scalar(select(func.count()).select_from(Submission).where(Submission.assignment_id == latest_assignment.id, Submission.status == "SUBMITTED")) if latest_assignment else 0

    history_filters = [Assignment.class_id == cid, Assignment.status.in_(["PUBLISHED", "CLOSED"])]
    if user.role == "STUDENT": history_filters.append(visible_assignment)
    recent_assignments = list(reversed(db.scalars(
        select(Assignment)
        .where(*history_filters)
        .order_by(Assignment.due_at.desc())
        .limit(6)
    ).all()))
    recent_assignment_ids = [item.id for item in recent_assignments]
    submitted_counts = dict(db.execute(
        select(Submission.assignment_id, func.count())
        .where(Submission.assignment_id.in_(recent_assignment_ids), Submission.status == "SUBMITTED")
        .group_by(Submission.assignment_id)
    ).all()) if recent_assignment_ids else {}
    assignment_history = []
    for item in recent_assignments:
        expected = members if item.submitter_type == "INDIVIDUAL" else teams
        submitted = submitted_counts.get(item.id, 0)
        assignment_history.append({
            "id": str(item.id),
            "title": item.title,
            "due_at": item.due_at,
            "submitted": submitted,
            "expected": expected,
            "completion_rate": round(submitted * 100 / expected, 1) if expected else 0,
        })

    latest_submission = None
    if user.role == "TEACHER":
        submitted_rows = db.execute(
            select(Assignment, SubmissionVersion, Submission)
            .join(Submission, and_(Submission.assignment_id == Assignment.id, Submission.status == "SUBMITTED"))
            .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
            .where(
                Assignment.class_id == cid,
                Assignment.status.in_(["PUBLISHED", "CLOSED"]),
                Assignment.submitter_type == "INDIVIDUAL",
                ~select(SubmissionAssessment.id).where(
                    SubmissionAssessment.submission_version_id == SubmissionVersion.id,
                    SubmissionAssessment.kind == "TEACHER",
                    SubmissionAssessment.status == "PUBLISHED",
                ).exists(),
                select(VersionFile.file_id).where(VersionFile.version_id == SubmissionVersion.id).exists(),
            )
        ).all()
        if submitted_rows:
            assignment, version, submission_item = min(
                submitted_rows,
                key=lambda row: (abs((row.Assignment.due_at - now()).total_seconds()), -row.SubmissionVersion.submitted_at.timestamp()),
            )
            owner = db.get(User, submission_item.owner_user_id) if submission_item.owner_user_id else db.get(Team, submission_item.owner_team_id)
            latest_submission = {
                "assignment_id": str(assignment.id), "assignment_title": assignment.title,
                "submission_version_id": str(version.id), "owner": owner.display_name if isinstance(owner, User) else owner.name,
                "submitted_at": version.submitted_at, "due_at": assignment.due_at,
            }

    latest_campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.class_id == cid, ReviewCampaign.due_at <= now()).order_by(ReviewCampaign.due_at.desc()).limit(1))
    review_expected = review_completed = 0
    if latest_campaign:
        if latest_campaign.assignment_snapshot_at is not None:
            allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == latest_campaign.id)).all()
            review_expected = sum(item.status != "SKIPPED" for item in allocations)
            review_completed = sum(item.status == "COMPLETED" for item in allocations)
        else:
            review_expected = db.scalar(select(func.count(func.distinct(TeamMember.user_id))).where(TeamMember.class_id == cid, TeamMember.status == "ACTIVE")) or 0
            review_completed = db.scalar(select(func.count(func.distinct(PeerReview.reviewer_id))).where(PeerReview.campaign_id == latest_campaign.id, PeerReview.status == "VALID")) or 0
    latest_campaign_assignment = db.get(Assignment, latest_campaign.assignment_id) if latest_campaign else None
    return {
        "class": class_json(course),
        "summary": {
            "member_count": members,
            "team_count": teams,
            "ungrouped_member_count": ungrouped_members,
            "active_assignments": active,
            "submission_rate": round((assignment_submitted or 0) * 100 / assignment_expected, 1) if assignment_expected else 0,
            "submission_assignment_title": latest_assignment.title if latest_assignment else None,
            "submission_assignment_due_at": latest_assignment.due_at if latest_assignment else None,
            "peer_review_rate": round(review_completed * 100 / review_expected, 1) if review_expected else 0,
            "peer_review_assignment_title": latest_campaign_assignment.title if latest_campaign_assignment else None,
            "peer_review_due_at": latest_campaign.due_at if latest_campaign else None,
            "latest_submission": latest_submission,
        },
        "assignment_history": assignment_history,
    }
