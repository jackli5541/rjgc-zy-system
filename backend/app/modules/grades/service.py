from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from uuid import UUID

from app.models import Assignment, CAPSTONE_STAGES, CapstoneStageGrade, ClassMember, Grade, GradeCoefficient, PeerReview, ReviewCampaign, Submission, SubmissionAssessment, SubmissionVersion, Team, User
from app.core.deps import membership, user_class
from app.core.errors import ApiError
from app.modules.assignments.service import build_submission_grade_result, displayed_submission_grade_result, latest_personal_submission, missing_submission_grade_result
from app.modules.members.service import team_json

GRADE_PERCENT = {"A": 95, "B": 85, "C": 75, "D": 60, "E": 0}


def kind_component_averages(db: Session, class_id: UUID, kind: str, student_ids: list[UUID]) -> dict[UUID, float]:
    """Average each student's letter grades (via GRADE_PERCENT) across published/closed individual
    assignments of the given kind (ASSIGNMENT/EXPERIMENT). Students with no graded item are omitted."""
    assignments = db.scalars(select(Assignment).where(
        Assignment.class_id == class_id, Assignment.kind == kind, Assignment.submitter_type == "INDIVIDUAL",
        Assignment.status.in_(["PUBLISHED", "CLOSED"]),
    )).all()
    totals: dict[UUID, float] = {}
    counts: dict[UUID, int] = {}
    for assignment in assignments:
        version_by_student = dict(db.execute(
            select(Submission.owner_user_id, SubmissionVersion)
            .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
            .where(Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED", Submission.owner_user_id.in_(student_ids))
        ).all())
        version_ids = [version.id for version in version_by_student.values()]
        assessments_by_version: dict[UUID, list[SubmissionAssessment]] = {}
        if version_ids:
            for item in db.scalars(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id.in_(version_ids))).all():
                assessments_by_version.setdefault(item.submission_version_id, []).append(item)
        missing_grade = missing_submission_grade_result(assignment)["final_grade"]
        for student_id in student_ids:
            version = version_by_student.get(student_id)
            if version:
                final_grade = build_submission_grade_result(assessments_by_version.get(version.id, []), lambda item: None)["final_grade"]
            else:
                final_grade = missing_grade
            if final_grade:
                totals[student_id] = totals.get(student_id, 0) + GRADE_PERCENT[final_grade]
                counts[student_id] = counts.get(student_id, 0) + 1
    return {student_id: totals[student_id] / counts[student_id] for student_id in counts}


def capstone_component_averages(db: Session, class_id: UUID, student_ids: list[UUID]) -> dict[UUID, float]:
    grades_by_student: dict[UUID, dict[str, CapstoneStageGrade]] = {}
    for grade in db.scalars(select(CapstoneStageGrade).where(CapstoneStageGrade.class_id == class_id)).all():
        grades_by_student.setdefault(grade.student_user_id, {})[grade.stage] = grade
    result = {}
    for student_id in student_ids:
        stage_grades = grades_by_student.get(student_id, {})
        scores = [stage_grades[stage].score for stage in CAPSTONE_STAGES if stage_grades.get(stage) and stage_grades[stage].score is not None]
        if len(scores) == len(CAPSTONE_STAGES):
            result[student_id] = float(sum(scores)) / len(CAPSTONE_STAGES)
    return result


def composite_grade_letter(score: float) -> str:
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "E"


def require_grade_assignment(db: Session, user: User, assignment_id: UUID) -> tuple[Assignment, ReviewCampaign]:
    assignment = db.get(Assignment, assignment_id)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment_id, ReviewCampaign.assignment_snapshot_at.is_not(None)))
    if not campaign: raise ApiError(404, "GRADEBOOK_NOT_FOUND", "该作业没有一对一互评成绩")
    return assignment, campaign


def export_rows(kind: str, class_id: UUID, user: User, db: Session, assignment_id: UUID | None = None) -> list[list]:
    rows: list[list] = []
    state_labels = {"ACTIVE": "正常", "ARCHIVED": "已归档", "LEFT": "已退出", "DISBANDED": "已解散", "PUBLISHED": "已发布", "DRAFT": "草稿", "CLOSED": "已结束", "VALID": "有效", "INVALID": "已作废"}
    if kind == "members":
        rows.append(["学号", "姓名", "状态", "小组"])
        for member, person in db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == class_id)):
            team = membership(db, class_id, person.id)
            rows.append([person.login_name, person.display_name, state_labels.get(member.status, member.status), team[1].name if team else ""])
    elif kind == "teams":
        rows.append(["小组", "组长", "人数", "选题", "状态"])
        for team in db.scalars(select(Team).where(Team.class_id == class_id)):
            item = team_json(db, team, user); rows.append([item["name"], item["leader_name"], item["member_count"], item["topic"]["name"] if item["topic"] else "", state_labels.get(item["status"], item["status"])])
    elif kind == "grades":
        if assignment_id is None: raise ApiError(422, "ASSIGNMENT_REQUIRED", "导出成绩时必须选择单次作业")
        assignment = db.get(Assignment, assignment_id)
        if not assignment or assignment.class_id != class_id: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
        has_current_assessments = bool(db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.assignment_id == assignment_id).limit(1)))
        legacy_grades = db.scalars(select(Grade).where(Grade.assignment_id == assignment_id)).all()
        if legacy_grades and not has_current_assessments:
            rows.append(["作业", "学号", "姓名", "小组", "互评分", "小组系数", "最终分", "状态"])
            grade_rows = db.execute(
                select(Grade, User, GradeCoefficient, Team)
                .join(User, User.id == Grade.subject_user_id)
                .outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
                .outerjoin(Team, Team.id == GradeCoefficient.team_id)
                .where(Grade.assignment_id == assignment_id)
                .order_by(Team.name, User.login_name)
            ).all()
            for grade, person, coefficient, team_item in grade_rows:
                if grade.peer_score is None: status = "待处理"
                elif not coefficient or coefficient.draft_value is None: status = "待填系数"
                elif grade.status == "PUBLISHED" and grade.draft_score != grade.score: status = "有未发布修改"
                elif grade.status == "PUBLISHED": status = "已发布"
                else: status = "待发布"
                rows.append([assignment.title, person.login_name, person.display_name, team_item.name if team_item else "未分组", grade.peer_score, coefficient.draft_value if coefficient else None, grade.draft_score, status])
        else:
            rows.append(["作业", "学号", "姓名", "小组", "提交状态", "学生互评等级", "教师等级", "最终等级", "成绩来源", "评分状态"])
            people = db.execute(select(ClassMember, User).join(User).where(ClassMember.class_id == class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT").order_by(User.login_name)).all()
            for _, person in people:
                team_row = membership(db, class_id, person.id)
                submitted = latest_personal_submission(db, assignment.id, person.id)
                if not submitted:
                    result = missing_submission_grade_result(assignment)
                    rows.append([assignment.title, person.login_name, person.display_name, team_row[1].name if team_row else "未分组", "未提交", "", "", result["final_grade"] or "", "系统判定" if result["grade_source"] == "SYSTEM" else "", "已评分" if result["final_grade"] else "未评分"])
                    continue
                _, version = submitted
                result = displayed_submission_grade_result(db, version)
                rows.append([
                    assignment.title, person.login_name, person.display_name, team_row[1].name if team_row else "未分组", "已提交",
                    result["peer_grade"] or "", result["teacher_grade"]["grade"] if result["teacher_grade"] else "", result["final_grade"] or "",
                    "教师评分" if result["grade_source"] == "TEACHER" else "学生互评" if result["grade_source"] == "PEER" else "",
                    "已评分" if result["final_grade"] else "待评分",
                ])
    else:
        rows.append(["作业", "评价人", "被评价人", "评价结果", "状态", "评语", "评价时间"])
        current_assignment_ids = set()
        direct_reviews = db.execute(select(SubmissionAssessment, Assignment).join(Assignment, Assignment.id == SubmissionAssessment.assignment_id).where(Assignment.class_id == class_id, SubmissionAssessment.kind == "PEER").order_by(SubmissionAssessment.updated_at.desc())).all()
        for review, assignment in direct_reviews:
            current_assignment_ids.add(assignment.id)
            rows.append([assignment.title, db.get(User, review.evaluator_id).display_name, db.get(User, review.subject_user_id).display_name, review.grade, state_labels.get(review.status, review.status), review.comment, review.published_at or review.updated_at])
        for review, assignment in db.execute(select(PeerReview, Assignment).join(ReviewCampaign, ReviewCampaign.id == PeerReview.campaign_id).join(Assignment).where(ReviewCampaign.class_id == class_id)):
            if assignment.id in current_assignment_ids: continue
            rows.append([assignment.title, db.get(User, review.reviewer_id).display_name, db.get(User, review.reviewee_id).display_name, review.total_score, state_labels.get(review.status, review.status), review.comment, review.updated_at])
    return rows


# 固定 UTC+8：中国自 1991 年起不再使用夏令时，与 ZoneInfo("Asia/Shanghai") 结果一致，
# 但不依赖 IANA 时区库——Windows 不自带该库，用 ZoneInfo 会让所有导出直接失败。
CHINA_TZ = timezone(timedelta(hours=8))


def export_cell(value):
    if isinstance(value, datetime):
        localized = value.astimezone(CHINA_TZ) if value.tzinfo else value
        return localized.strftime("%Y-%m-%d %H:%M:%S")
    return value
