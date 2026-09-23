from __future__ import annotations

from fastapi import APIRouter, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from uuid import UUID

from app.grading import finalize_campaign
from app.models import Assignment, ClassMember, FileObject, Grade, PeerReview, ReviewAssignment, ReviewCampaign, Submission, SubmissionAssessment, SubmissionVersion, Team, TeamMember, User, VersionFile
from app.core.audit import audit, notify
from app.core.deps import CsrfUser, CurrentUser, Db, membership, require_class, require_team, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.html import clean_html
from app.core.schemas import ReasonIn
from app.core.utils import now
from app.modules.assignments.schemas import AllocatedCampaignIn, PeerSubmissionAssessmentIn, ReviewIn, SubmissionFeedbackIn
from app.modules.assignments.service import assessment_json, assignment_json, feedback_json, file_json, latest_personal_submission, lock_submission_version, own_submission, peer_assessment_for_version, peer_assessment_summary, peer_feedback_context, replace_feedback_annotations, require_peer_review_submission, submission_grade_result, validate_feedback_annotations, writable_teacher_classes

router = APIRouter()

@router.get("/api/v1/peer-review-assignments")
def peer_review_assignments(user: CurrentUser, db: Db, class_id: UUID = Query()):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    require_class(db, user, class_id)
    _, team = require_team(db, class_id, user)
    teammate_ids = select(TeamMember.user_id).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE", TeamMember.user_id != user.id)
    items = []
    assignments = db.scalars(select(Assignment).where(Assignment.class_id == class_id, Assignment.submitter_type == "INDIVIDUAL", Assignment.status.in_(["PUBLISHED", "CLOSED"])).order_by(Assignment.created_at.desc())).all()
    for assignment in assignments:
        if not latest_personal_submission(db, assignment.id, user.id):
            continue
        versions = db.execute(
            select(SubmissionVersion.id, Submission.owner_user_id, User.display_name, User.login_name)
            .join(Submission, Submission.id == SubmissionVersion.submission_id)
            .join(User, User.id == Submission.owner_user_id)
            .where(Submission.assignment_id == assignment.id, Submission.owner_user_id.in_(teammate_ids), Submission.status == "SUBMITTED", SubmissionVersion.version_no == Submission.current_version_no)
            .order_by(User.login_name)
        ).all()
        if not versions: continue
        version_ids = [row.id for row in versions]
        reviewed_version_ids = set(db.scalars(select(SubmissionAssessment.submission_version_id).where(
            SubmissionAssessment.submission_version_id.in_(version_ids),
            SubmissionAssessment.kind == "PEER",
            SubmissionAssessment.status == "PUBLISHED",
        )).all())
        candidates = [
            {
                "user_id": str(row.owner_user_id), "name": row.display_name, "student_no": row.login_name,
                "reviewed": row.id in reviewed_version_ids,
            }
            for row in versions
        ]
        payload = assignment_json(assignment)
        payload.update({"assignment_id": str(assignment.id), "assignment_title": assignment.title, "available_count": len(versions), "reviewed_count": len(reviewed_version_ids), "pending_count": len(versions) - len(reviewed_version_ids), "candidates": candidates})
        items.append(payload)
    return {"items": items, "total": len(items)}


@router.get("/api/v1/assignments/{aid}/peer-review")
def peer_review_detail(aid: UUID, user: CurrentUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or assignment.status not in {"PUBLISHED", "CLOSED"}: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_class(db, user, assignment.class_id)
    require_peer_review_submission(db, aid, user.id)
    _, team = require_team(db, assignment.class_id, user)
    attachments = db.scalars(
        select(FileObject)
        .where(FileObject.assignment_id == aid, FileObject.purpose == "ATTACHMENT", FileObject.active == True, or_(FileObject.material_type.is_(None), FileObject.material_type != "CRITERIA"))  # noqa: E712
        .order_by(FileObject.created_at)
    ).all()
    criteria_files = db.scalars(
        select(FileObject)
        .where(
            FileObject.assignment_id == aid,
            FileObject.active == True,  # noqa: E712
            FileObject.purpose == "REVIEW_CRITERIA",
        )
        .order_by(FileObject.created_at)
    ).all()
    review_criteria = db.scalars(
        select(FileObject)
        .where(
            FileObject.assignment_id == aid,
            FileObject.purpose == "ATTACHMENT",
            FileObject.material_type == "CRITERIA",
            FileObject.active == True,  # noqa: E712
        )
        .order_by(FileObject.created_at)
    ).all()
    reviewer_submission, _ = own_submission(db, assignment, user)
    criteria_unlocked = bool(reviewer_submission and reviewer_submission.status == "SUBMITTED")
    rows = db.execute(
        select(Submission, SubmissionVersion, User)
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .join(User, User.id == Submission.owner_user_id)
        .join(TeamMember, and_(TeamMember.user_id == Submission.owner_user_id, TeamMember.team_id == team.id, TeamMember.status == "ACTIVE"))
        .where(Submission.assignment_id == aid, Submission.owner_user_id != user.id, Submission.status == "SUBMITTED")
        .order_by(User.login_name)
    ).all()
    candidates = []
    for submission_item, version, person in rows:
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
        claimed_review = peer_assessment_for_version(db, version.id)
        own_review = claimed_review if claimed_review and claimed_review.evaluator_id == user.id else None
        was_peer_reviewed = bool(claimed_review and claimed_review.status == "PUBLISHED")
        candidates.append({
            "user_id": str(person.id), "name": person.display_name, "student_no": person.login_name,
            "submitted_at": version.submitted_at, "submission_version_id": str(version.id),
            "grade_cap": "B" if version.grade_cap == "B" or was_peer_reviewed else None,
            "files": [file_json(file) for file in files],
            "review": assessment_json(db, own_review) if own_review else (peer_assessment_summary(db, claimed_review, user.id) if claimed_review else None),
            "can_review": claimed_review is None or bool(own_review),
            "can_edit": bool(own_review),
        })
    return {
        "assignment": assignment_json(assignment),
        "attachments": [file_json(file) for file in attachments],
        "review_criteria": [file_json(file) for file in review_criteria] if criteria_unlocked else [],
        "review_criteria_locked": bool(review_criteria and not criteria_unlocked),
        "criteria_files": [file_json(file) for file in criteria_files],
        "team": {"id": str(team.id), "name": team.name},
        "candidates": candidates,
    }


@router.post("/api/v1/assignments/{aid}/peer-reviews", status_code=201)
def save_peer_submission_assessment(aid: UUID, data: PeerSubmissionAssessmentIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生使用")
    assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or assignment.status not in {"PUBLISHED", "CLOSED"}: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    require_peer_review_submission(db, aid, user.id)
    if data.reviewee_id == user.id: raise ApiError(422, "SELF_REVIEW_FORBIDDEN", "不能评价自己的作业")
    reviewer_team = membership(db, assignment.class_id, user.id)
    reviewee_team = membership(db, assignment.class_id, data.reviewee_id)
    if not reviewer_team or not reviewee_team or reviewer_team[1].id != reviewee_team[1].id: raise ApiError(403, "TEAM_REVIEW_ONLY", "只能评价本组成员的作业")
    submitted = latest_personal_submission(db, aid, data.reviewee_id)
    if not submitted: raise ApiError(409, "REVIEWEE_NOT_SUBMITTED", "该组员尚未提交作业")
    _, version = submitted
    lock_submission_version(db, version.id)
    item = peer_assessment_for_version(db, version.id)
    if item and item.evaluator_id != user.id:
        evaluator = db.get(User, item.evaluator_id)
        raise ApiError(409, "PEER_REVIEW_TAKEN", f"该作品已由{evaluator.display_name}评价，不能重复评价或修改")
    was_peer_reviewed = bool(item and item.status == "PUBLISHED")
    if data.grade == "A" and (version.grade_cap == "B" or was_peer_reviewed):
        raise ApiError(409, "GRADE_CAP_EXCEEDED", "该作业已被互评，后续学生互评最高成绩为 B")
    updating = item is not None
    if item:
        item.grade, item.comment, item.status, item.published_at = data.grade, data.comment.strip(), "PUBLISHED", now()
        item.version += 1
    else:
        item = SubmissionAssessment(assignment_id=aid, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=data.reviewee_id, kind="PEER", grade=data.grade, comment=data.comment.strip(), status="PUBLISHED", published_at=now())
        db.add(item)
    db.flush(); audit(db, user, "PEER_ASSESSMENT_UPDATED" if updating else "PEER_ASSESSMENT_SUBMITTED", "submission_assessment", str(item.id), {"grade": data.grade, "subject_user_id": str(data.reviewee_id)}); db.commit()
    return {**assessment_json(db, item), "updated": updating}


@router.get("/api/v1/submission-versions/{version_id}/peer-feedback")
def get_peer_submission_feedback(version_id: UUID, user: CurrentUser, db: Db):
    version, _, _ = peer_feedback_context(db, version_id, user)
    item = peer_assessment_for_version(db, version.id)
    if item and item.evaluator_id != user.id:
        evaluator = db.get(User, item.evaluator_id)
        raise ApiError(409, "PEER_REVIEW_TAKEN", f"该作品已由{evaluator.display_name}评价，不能重复评价或修改")
    return feedback_json(db, item)


@router.post("/api/v1/submission-versions/{version_id}/peer-feedback/publish")
def publish_peer_submission_feedback(version_id: UUID, data: SubmissionFeedbackIn, user: CsrfUser, db: Db):
    version, submission_item, assignment = peer_feedback_context(db, version_id, user)
    require_writable_class(db, user, assignment.class_id)
    lock_submission_version(db, version.id)
    item = peer_assessment_for_version(db, version.id)
    if item and item.evaluator_id != user.id:
        evaluator = db.get(User, item.evaluator_id)
        raise ApiError(409, "PEER_REVIEW_TAKEN", f"该作品已由{evaluator.display_name}评价，不能重复评价或修改")
    current_revision = item.version if item else 0
    if data.revision != current_revision: raise ApiError(409, "FEEDBACK_VERSION_CONFLICT", "反馈已在其他页面更新，请刷新后重试")
    if data.grade == "A" and version.grade_cap == "B":
        raise ApiError(409, "GRADE_CAP_EXCEEDED", "该作业已被互评，后续学生互评最高成绩为 B")
    annotations = validate_feedback_annotations(db, version.id, data.annotations)
    comment = clean_html(data.comment)
    updating = item is not None
    if item:
        item.grade, item.comment, item.status, item.published_at, item.draft_payload = data.grade, comment, "PUBLISHED", now(), None
        item.version += 1
    else:
        item = SubmissionAssessment(assignment_id=assignment.id, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=submission_item.owner_user_id, kind="PEER", grade=data.grade, comment=comment, status="PUBLISHED", published_at=now())
        db.add(item); db.flush()
    replace_feedback_annotations(db, item, annotations, user)
    audit(db, user, "PEER_ASSESSMENT_UPDATED" if updating else "PEER_ASSESSMENT_SUBMITTED", "submission_assessment", str(item.id), {"grade": data.grade, "subject_user_id": str(submission_item.owner_user_id), "annotation_count": len(annotations)})
    db.commit(); db.refresh(item)
    return {**feedback_json(db, item), "updated": updating, "result": submission_grade_result(db, version)}


@router.post("/api/v1/review-campaigns", status_code=201)
def create_campaign(data: AllocatedCampaignIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.scalar(select(Assignment).where(Assignment.id == data.assignment_id).with_for_update())
    if not assignment: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    writable_teacher_classes(db, user, [assignment.class_id])
    if assignment.submitter_type != "INDIVIDUAL": raise ApiError(422, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "互评只能关联个人作业")
    if assignment.due_at >= now(): raise ApiError(409, "ASSIGNMENT_NOT_CLOSED", "作业截止后才能创建互评")
    if data.due_at <= now(): raise ApiError(422, "CAMPAIGN_TIME_INVALID", "互评截止时间必须晚于当前时间")
    if db.scalar(select(ReviewCampaign.id).where(ReviewCampaign.assignment_id == assignment.id)): raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
    criteria_ids = set(data.criteria_file_ids)
    criteria_files = db.scalars(select(FileObject).where(FileObject.id.in_(criteria_ids), FileObject.assignment_id == assignment.id, FileObject.purpose == "REVIEW_CRITERIA")).all() if criteria_ids else []
    if len(criteria_files) != len(criteria_ids): raise ApiError(422, "CRITERIA_FILE_INVALID", "互评标准附件不存在或不属于关联作业")
    if not data.criteria_text.strip() and not criteria_files: raise ApiError(422, "REVIEW_CRITERIA_REQUIRED", "互评标准文字和附件至少提供一种")

    frozen_rows = db.execute(
        select(User, SubmissionVersion)
        .join(ClassMember, and_(ClassMember.user_id == User.id, ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT"))
        .join(Submission, and_(Submission.owner_user_id == User.id, Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED"))
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(User.status == "ACTIVE")
        .order_by(User.login_name)
        .with_for_update()
    ).all()
    if len(frozen_rows) < 2: raise ApiError(409, "REVIEW_CANDIDATES_INSUFFICIENT", "全班已正式提交学生少于 2 人，不能创建互评")

    snapshot_at = now()
    campaign = ReviewCampaign(assignment_id=assignment.id, class_id=assignment.class_id, mode=data.mode, criteria_text=data.criteria_text.strip(), assignment_snapshot_at=snapshot_at, rubric=[{"key": "score", "label": "总分", "weight": 100}], comment_min_length=1, due_at=data.due_at, publish_at=snapshot_at, require_all=False, allow_update=True)
    db.add(campaign); db.flush()
    warnings = []
    team_by_user = {
        user_id: team_id
        for user_id, team_id in db.execute(
            select(TeamMember.user_id, TeamMember.team_id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.class_id == assignment.class_id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")
        ).all()
    }
    if data.mode == "CLASS":
        groups = [("CLASS", "教学班", frozen_rows)]
    else:
        grouped = {(team.id, team.name): [] for team in db.scalars(select(Team).where(Team.class_id == assignment.class_id, Team.status == "ACTIVE")).all()}
        for person, version in frozen_rows:
            team_row = db.execute(select(TeamMember.team_id, Team.name).join(Team, Team.id == TeamMember.team_id).where(TeamMember.class_id == assignment.class_id, TeamMember.user_id == person.id, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")).first()
            key, label = (team_row.team_id, team_row.name) if team_row else (None, "未分组")
            grouped.setdefault((key, label), []).append((person, version))
        groups = [(str(key), label, rows) for (key, label), rows in grouped.items()]
    allocations = []
    for _, label, rows in groups:
        if len(rows) < 2:
            reason = f"{label} 已正式提交人数少于 2 人"
            warnings.append({"group": label, "reason": reason, "count": len(rows)})
            for person, _ in rows:
                allocations.append(ReviewAssignment(campaign_id=campaign.id, reviewer_id=person.id, participant_team_id=team_by_user.get(person.id), status="SKIPPED", skip_reason=reason))
            continue
        for index, (reviewer, _) in enumerate(rows):
            reviewee, version = rows[(index + 1) % len(rows)]
            allocations.append(ReviewAssignment(campaign_id=campaign.id, reviewer_id=reviewer.id, participant_team_id=team_by_user.get(reviewer.id), reviewee_id=reviewee.id, submission_version_id=version.id))
            notify(db, reviewer.id, "REVIEW_ASSIGNED", f"新的互评任务：{assignment.title}")
    db.add_all(allocations)
    audit(db, user, "REVIEW_CAMPAIGN_CREATED", "review_campaign", str(campaign.id), {"mode": data.mode, "allocated": sum(x.status == "PENDING" for x in allocations), "skipped": sum(x.status == "SKIPPED" for x in allocations)})
    try: db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "CAMPAIGN_EXISTS", "该作业已创建互评活动")
    return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "status": campaign.status, "mode": campaign.mode, "assignment_snapshot_at": campaign.assignment_snapshot_at, "allocated": sum(x.status == "PENDING" for x in allocations), "skipped": sum(x.status == "SKIPPED" for x in allocations), "warnings": warnings}


@router.get("/api/v1/review-campaigns")
def campaigns(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    query = select(ReviewCampaign, Assignment).join(Assignment).where(ReviewCampaign.class_id == class_id, Assignment.submitter_type == "INDIVIDUAL")
    if user.role == "STUDENT": query = query.where(or_(ReviewCampaign.publish_at.is_(None), ReviewCampaign.publish_at <= now()))
    rows = db.execute(query.order_by(ReviewCampaign.due_at.desc())).all()
    items = []
    for c, a in rows:
        payload = {"id": str(c.id), "assignment_id": str(a.id), "assignment_title": a.title, "mode": c.mode, "criteria_text": c.criteria_text, "assignment_snapshot_at": c.assignment_snapshot_at, "rubric": c.rubric, "comment_min_length": c.comment_min_length, "due_at": c.due_at, "publish_at": c.publish_at, "require_all": c.require_all, "allow_update": c.allow_update, "status": c.status, "grades_generated_at": c.grades_generated_at, "version": c.version, "completed": db.scalar(select(func.count()).select_from(PeerReview).where(PeerReview.campaign_id == c.id, PeerReview.status == "VALID")) or 0}
        if user.role == "STUDENT":
            allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == c.id, ReviewAssignment.reviewer_id == user.id))
            payload["pending_count"] = 1 if allocation and allocation.status == "PENDING" else 0
            payload["allocation_status"] = allocation.status if allocation else None
            payload["skip_reason"] = allocation.skip_reason if allocation else None
        items.append(payload)
    return {"items": items, "total": len(items)}


@router.get("/api/v1/review-campaigns/{cid}/assignment")
def allocated_assignment(cid: UUID, user: CurrentUser, db: Db):
    campaign = db.get(ReviewCampaign, cid)
    if not campaign: raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_class(db, user, campaign.class_id)
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "该接口仅供学生查看自己的互评任务")
    allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == cid, ReviewAssignment.reviewer_id == user.id))
    if not allocation: raise ApiError(404, "REVIEW_ASSIGNMENT_NOT_FOUND", "当前活动没有分配给你的任务")
    assignment = db.get(Assignment, campaign.assignment_id)
    if not assignment or assignment.submitter_type != "INDIVIDUAL":
        raise ApiError(404, "CAMPAIGN_NOT_FOUND", "小组作业不参与互评")
    criteria_files = db.scalars(select(FileObject).where(FileObject.assignment_id == campaign.assignment_id, FileObject.purpose == "REVIEW_CRITERIA").order_by(FileObject.created_at)).all()
    payload = {
        "id": str(allocation.id), "status": allocation.status, "skip_reason": allocation.skip_reason,
        "campaign": {"id": str(campaign.id), "assignment_title": assignment.title, "mode": campaign.mode, "criteria_text": campaign.criteria_text or "", "due_at": campaign.due_at, "assignment_snapshot_at": campaign.assignment_snapshot_at, "criteria_files": [file_json(file, db.get(User, file.owner_id).display_name) for file in criteria_files]},
        "reviewee": None, "submission": None, "review": None,
    }
    if allocation.reviewee_id and allocation.submission_version_id:
        reviewee = db.get(User, allocation.reviewee_id); version = db.get(SubmissionVersion, allocation.submission_version_id)
        files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
        review = db.scalar(select(PeerReview).where(PeerReview.allocation_id == allocation.id, PeerReview.status == "VALID"))
        payload["reviewee"] = {"id": str(reviewee.id), "name": reviewee.display_name, "student_no": reviewee.login_name}
        payload["submission"] = {"submitted_at": version.submitted_at, "files": [file_json(file, reviewee.display_name, True) for file in files]}
        if review: payload["review"] = {"id": str(review.id), "score": review.total_score, "comment": review.comment, "status": review.status}
    return payload


@router.post("/api/v1/review-campaigns/{cid}/reviews", status_code=201)
def review(cid: UUID, data: ReviewIn, user: CsrfUser, db: Db):
    c = db.get(ReviewCampaign, cid)
    if not c or c.status != "ACTIVE" or (c.publish_at and c.publish_at > now()) or c.due_at < now(): raise ApiError(409, "CAMPAIGN_CLOSED", "互评活动未开放或已截止")
    assignment = db.get(Assignment, c.assignment_id)
    if not assignment or assignment.submitter_type != "INDIVIDUAL":
        raise ApiError(409, "INDIVIDUAL_ASSIGNMENT_REQUIRED", "小组作业不参与互评")
    require_writable_class(db, user, c.class_id)
    allocation = db.scalar(select(ReviewAssignment).where(ReviewAssignment.campaign_id == c.id, ReviewAssignment.reviewer_id == user.id).with_for_update())
    if not allocation: raise ApiError(403, "REVIEW_NOT_ASSIGNED", "当前活动没有分配给你的互评任务")
    if allocation.status == "SKIPPED": raise ApiError(409, "REVIEW_ASSIGNMENT_SKIPPED", allocation.skip_reason or "该互评任务已跳过")
    if allocation.status not in {"PENDING", "COMPLETED"}: raise ApiError(409, "REVIEW_DUPLICATE", "该互评任务已提交")
    if allocation.status == "COMPLETED" and not c.allow_update: raise ApiError(409, "REVIEW_UPDATE_DISABLED", "当前互评活动不允许修改已提交评价")
    if data.score is None: raise ApiError(422, "SCORE_REQUIRED", "请填写 0 至 100 的总分")
    comment = data.comment.strip()
    if not comment: raise ApiError(422, "COMMENT_REQUIRED", "评语不能为空")
    existing = db.scalar(select(PeerReview).where(PeerReview.allocation_id == allocation.id))
    updating = allocation.status == "COMPLETED"
    if updating and not existing: raise ApiError(409, "REVIEW_UPDATE_INVALID", "已提交评价记录不存在，请联系教师处理")
    scores = {"score": data.score}
    if existing:
        existing.reviewer_id, existing.reviewee_id, existing.submission_version_id = allocation.reviewer_id, allocation.reviewee_id, allocation.submission_version_id
        existing.scores, existing.total_score, existing.comment, existing.status, existing.invalid_reason = scores, data.score, comment, "VALID", None
        item = existing
    else:
        item = PeerReview(allocation_id=allocation.id, campaign_id=c.id, reviewer_id=allocation.reviewer_id, reviewee_id=allocation.reviewee_id, submission_version_id=allocation.submission_version_id, scores=scores, total_score=data.score, comment=comment)
        db.add(item)
    allocation.status = "COMPLETED"
    if not updating: notify(db, allocation.reviewee_id, "REVIEW_RECEIVED", f"收到来自 {user.display_name} 的作品评价")
    db.flush(); audit(db, user, "PEER_REVIEW_UPDATED" if updating else "PEER_REVIEW_SUBMITTED", "peer_review", str(item.id), {"allocation_id": str(allocation.id)}); db.commit()
    return {"id": str(item.id), "allocation_id": str(allocation.id), "total_score": data.score, "status": item.status, "updated": updating}


@router.get("/api/v1/peer-reviews/received")
def received(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id); reviewer = aliased(User)
    result_visible = or_(ReviewCampaign.due_at <= now(), ReviewCampaign.status == "CLOSED")
    rows = db.execute(select(PeerReview, Assignment, reviewer).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment, Assignment.id == ReviewCampaign.assignment_id).join(reviewer, reviewer.id == PeerReview.reviewer_id).where(PeerReview.reviewee_id == user.id, PeerReview.status == "VALID", ReviewCampaign.class_id == class_id, result_visible)).all()
    return {"items": [{"id": str(r.id), "campaign_id": str(r.campaign_id), "assignment_title": a.title, "reviewer_name": p.display_name, "scores": r.scores, "total_score": r.total_score, "comment": r.comment, "created_at": r.created_at} for r, a, p in rows]}


@router.get("/api/v1/peer-reviews/sent")
def sent_reviews(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    reviewee = aliased(User)
    rows = db.execute(select(PeerReview, Assignment, reviewee).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment, Assignment.id == ReviewCampaign.assignment_id).join(reviewee, reviewee.id == PeerReview.reviewee_id).where(PeerReview.reviewer_id == user.id, ReviewCampaign.class_id == class_id).order_by(PeerReview.updated_at.desc())).all()
    return {"items": [{"id": str(r.id), "campaign_id": str(r.campaign_id), "assignment_title": a.title, "reviewee_name": p.display_name, "scores": r.scores, "total_score": r.total_score, "comment": r.comment, "status": r.status, "created_at": r.created_at, "updated_at": r.updated_at} for r, a, p in rows]}


@router.post("/api/v1/peer-reviews/{rid}/invalidate", status_code=204)
def invalidate(rid: UUID, data: ReasonIn, user: CsrfUser, db: Db):
    teacher(user); x = db.get(PeerReview, rid)
    if not x: raise ApiError(404, "REVIEW_NOT_FOUND", "评价不存在")
    campaign = db.get(ReviewCampaign, x.campaign_id)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "REVIEW_NOT_FOUND", "评价不存在")
    require_writable_class(db, user, campaign.class_id)
    grade = db.scalar(select(Grade).where(Grade.peer_review_id == x.id))
    if grade and grade.status == "PUBLISHED": raise ApiError(409, "PUBLISHED_GRADE_LOCKED", "该评价已形成发布成绩，不能再作废")
    x.status, x.invalid_reason = "INVALID", data.reason
    if x.allocation_id:
        allocation = db.get(ReviewAssignment, x.allocation_id)
        if allocation: allocation.status = "PENDING"
    if grade:
        grade.peer_review_id, grade.peer_score, grade.draft_score, grade.status = None, None, None, "PENDING"
        grade.version += 1
    audit(db, user, "PEER_REVIEW_INVALIDATED", "peer_review", str(x.id), {"reason": data.reason}); db.commit(); return Response(status_code=204)


@router.get("/api/v1/review-campaigns/{cid}/reviews")
def campaign_reviews(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); campaign = db.get(ReviewCampaign, cid)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    reviewer = aliased(User); reviewee = aliased(User)
    rows = db.execute(select(PeerReview, reviewer, reviewee).join(reviewer, reviewer.id == PeerReview.reviewer_id).join(reviewee, reviewee.id == PeerReview.reviewee_id).where(PeerReview.campaign_id == cid).order_by(PeerReview.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "reviewer_name": from_user.display_name, "reviewee_name": to_user.display_name, "total_score": item.total_score, "comment": item.comment, "status": item.status, "invalid_reason": item.invalid_reason, "created_at": item.created_at} for item, from_user, to_user in rows], "total": len(rows)}


@router.post("/api/v1/review-campaigns/{cid}/close")
def close_campaign(cid: UUID, user: CsrfUser, db: Db):
    teacher(user); campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == cid).with_for_update())
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    require_writable_class(db, user, campaign.class_id)
    if campaign.status == "CLOSED":
        if campaign.grades_generated_at is None:
            finalize_campaign(db, campaign, now())
            db.commit()
        return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "due_at": campaign.due_at, "status": campaign.status, "grades_generated_at": campaign.grades_generated_at, "version": campaign.version}
    if campaign.status != "ACTIVE": raise ApiError(409, "CAMPAIGN_NOT_ACTIVE", "当前互评活动不能提前截止")
    campaign.due_at = now()
    finalize_campaign(db, campaign, campaign.due_at)
    audit(db, user, "REVIEW_CAMPAIGN_CLOSED", "review_campaign", str(cid), {"due_at": campaign.due_at.isoformat()})
    db.commit()
    return {"id": str(campaign.id), "assignment_id": str(campaign.assignment_id), "due_at": campaign.due_at, "status": campaign.status, "grades_generated_at": campaign.grades_generated_at, "version": campaign.version}


@router.get("/api/v1/review-campaigns/{cid}/stats")
def campaign_stats(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); campaign = db.get(ReviewCampaign, cid)
    if not campaign or not user_class(db, user, campaign.class_id): raise ApiError(404, "CAMPAIGN_NOT_FOUND", "互评活动不存在")
    reviews = db.scalars(select(PeerReview).where(PeerReview.campaign_id == cid, PeerReview.status == "VALID")).all()
    if campaign.assignment_snapshot_at is not None:
        allocations = db.scalars(select(ReviewAssignment).where(ReviewAssignment.campaign_id == cid)).all()
        skipped_allocations = [item for item in allocations if item.status == "SKIPPED"]
        reviewer_names = {
            item.id: item.display_name
            for item in db.scalars(select(User).where(User.id.in_([allocation.reviewer_id for allocation in skipped_allocations]))).all()
        } if skipped_allocations else {}
        skipped = [{"reviewer_id": str(x.reviewer_id), "reviewer_name": reviewer_names.get(x.reviewer_id, ""), "reason": x.skip_reason} for x in skipped_allocations]
        assigned = sum(x.status != "SKIPPED" for x in allocations)
        completed = sum(x.status == "COMPLETED" for x in allocations)
        return {"assigned_count": assigned, "completed_count": completed, "skipped_count": len(skipped), "skipped": skipped, "completion_rate": round(completed * 100 / assigned, 1) if assigned else 0, "review_count": len(reviews), "reviewer_count": completed, "uncompleted_reviewer_count": max(assigned - completed, 0), "average_score": round(sum(x.total_score for x in reviews) / len(reviews), 2) if reviews else None, "received_count": {str(x.reviewee_id): 1 for x in reviews}}
    reviewers = len({x.reviewer_id for x in reviews}); received_count = {}
    for x in reviews: received_count[str(x.reviewee_id)] = received_count.get(str(x.reviewee_id), 0) + 1
    grouped = {}
    for member in db.scalars(select(TeamMember).join(Team).where(Team.class_id == campaign.class_id, Team.status == "ACTIVE", TeamMember.status == "ACTIVE")):
        grouped.setdefault(member.team_id, []).append(member.user_id)
    eligible_reviewers = sum(len(member_ids) for member_ids in grouped.values() if len(member_ids) > 1)
    return {"review_count": len(reviews), "reviewer_count": reviewers, "uncompleted_reviewer_count": max(eligible_reviewers - reviewers, 0), "average_score": round(sum(x.total_score for x in reviews) / len(reviews), 2) if reviews else None, "received_count": received_count}
