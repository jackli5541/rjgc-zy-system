from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select
from uuid import UUID

from app.grading import final_score
from app.models import Assignment, AttendanceRecord, AttendanceSession, ClassMember, FileObject, Grade, GradeCoefficient, GradeRevision, ReviewCampaign, Submission, SubmissionAssessment, SubmissionVersion, Team, TeamMember, User, VersionFile
from app.core.audit import audit, notify
from app.core.deps import CsrfUser, CurrentUser, Db, require_class, require_team, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.utils import now
from app.modules.assignments.service import displayed_submission_grade_result, file_json, latest_personal_submission, missing_submission_grade_result, submission_grade_result
from app.modules.grades.schemas import CoefficientIn, GradePublishIn
from app.modules.grades.service import capstone_component_averages, composite_grade_letter, kind_component_averages, require_grade_assignment

router = APIRouter()

@router.get("/api/v1/grades")
def grades(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id)
    if user.role == "STUDENT":
        _, team = require_team(db, class_id, user)
        assignments = db.scalars(select(Assignment).where(Assignment.class_id == class_id, Assignment.status.in_(["PUBLISHED", "CLOSED"])).order_by(Assignment.due_at.desc())).all()
        legacy_rows = db.execute(
            select(Grade, Assignment, GradeCoefficient).select_from(Grade).join(Assignment, Assignment.id == Grade.assignment_id).outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
            .where(Assignment.class_id == class_id, Grade.subject_user_id == user.id, Grade.status == "PUBLISHED")
        ).all()
        legacy_assignment_ids = {grade.assignment_id for grade, _, _ in legacy_rows}
        items = []
        for assignment in assignments:
            if assignment.submitter_type == "INDIVIDUAL":
                submitted = latest_personal_submission(db, assignment.id, user.id)
            else:
                submitted = db.execute(
                    select(Submission, SubmissionVersion)
                    .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
                    .where(Submission.assignment_id == assignment.id, Submission.owner_team_id == team.id, Submission.status == "SUBMITTED")
                ).first()
            if submitted:
                _, version = submitted
                has_current_assessment = bool(db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == version.id).limit(1)))
                if assignment.id in legacy_assignment_ids and not has_current_assessment: continue
                result = displayed_submission_grade_result(db, version)
                files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == version.id)).all()
                items.append({"id": str(version.id), "submission_version_id": str(version.id), "submission_version_no": version.version_no, "assignment_id": str(assignment.id), "assignment_title": assignment.title, "submitter_type": assignment.submitter_type, "status": result["grading_status"], "files": [file_json(file) for file in files], **result})
            else:
                result = missing_submission_grade_result(assignment)
                if result["final_grade"]:
                    items.append({"id": str(assignment.id), "submission_version_id": None, "submission_version_no": None, "assignment_id": str(assignment.id), "assignment_title": assignment.title, "submitter_type": assignment.submitter_type, "status": result["grading_status"], "files": [], **result})
        new_assignment_ids = {item["assignment_id"] for item in items}
        for grade, assignment, coefficient in legacy_rows:
            if str(assignment.id) not in new_assignment_ids:
                items.append({"id": str(grade.id), "assignment_id": str(assignment.id), "assignment_title": assignment.title, "peer_score": grade.peer_score, "coefficient": coefficient.published_value if coefficient else None, "score": grade.score, "status": grade.status})
        return {"items": items, "total": len(items)}
    query = select(Grade, Assignment, GradeCoefficient).select_from(Grade).join(Assignment, Assignment.id == Grade.assignment_id).outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id).where(Assignment.class_id == class_id)
    rows = db.execute(query.order_by(Grade.updated_at.desc())).all(); items = []
    for g, a, coefficient in rows:
        person = db.get(User, g.subject_user_id)
        team_item = db.get(Team, coefficient.team_id) if coefficient else None
        items.append({"id": str(g.id), "assignment_id": str(a.id), "assignment_title": a.title, "subject_id": str(person.id), "subject_name": person.display_name, "student_no": person.login_name, "team_name": team_item.name if team_item else "未分组", "peer_score": g.peer_score, "coefficient": coefficient.published_value if coefficient else None, "score": g.score, "status": g.status, "version": g.version})
    return {"items": items, "total": len(items)}


@router.get("/api/v1/grades/assignments")
def grade_assignments(user: CurrentUser, db: Db, class_id: UUID = Query()):
    teacher(user); require_class(db, user, class_id)
    rows = db.scalars(select(Assignment).where(Assignment.class_id == class_id, Assignment.submitter_type == "INDIVIDUAL").order_by(Assignment.due_at.desc())).all()
    total_students = db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.class_id == class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")) or 0
    items = []
    for assignment in rows:
        campaign = db.scalar(select(ReviewCampaign).where(ReviewCampaign.assignment_id == assignment.id))
        submissions = db.scalars(select(Submission).where(Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED")).all()
        graded = 0
        for submission_item in submissions:
            version = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == submission_item.id, SubmissionVersion.version_no == submission_item.current_version_no))
            if version and submission_grade_result(db, version)["final_grade"]: graded += 1
        if missing_submission_grade_result(assignment)["final_grade"]:
            graded += max(0, total_students - len(submissions))
        items.append({
            "id": str(assignment.id), "title": assignment.title, "due_at": assignment.due_at, "status": assignment.status,
            "campaign_id": str(campaign.id) if campaign else None, "campaign_status": campaign.status if campaign else None,
            "grades_generated_at": campaign.grades_generated_at if campaign else None,
            "total": total_students, "submitted": len(submissions), "graded": graded, "pending": max(0, total_students - graded),
        })
    return {"items": items, "total": len(items)}


@router.get("/api/v1/classes/{cid}/grade-overview")
def grade_overview(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); require_class(db, user, cid)
    rows = db.execute(
        select(ClassMember, User, Team.name)
        .select_from(ClassMember)
        .join(User, User.id == ClassMember.user_id)
        .outerjoin(TeamMember, and_(TeamMember.class_id == cid, TeamMember.user_id == User.id, TeamMember.status == "ACTIVE"))
        .outerjoin(Team, and_(Team.id == TeamMember.team_id, Team.status == "ACTIVE"))
        .where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")
        .order_by(ClassMember.joined_at, ClassMember.id)
    ).all()
    student_ids = [student.id for _, student, _ in rows]
    homework_avg = kind_component_averages(db, cid, "ASSIGNMENT", student_ids)
    lab_avg = kind_component_averages(db, cid, "EXPERIMENT", student_ids)
    capstone_avg = capstone_component_averages(db, cid, student_ids)
    attendance_deductions = {}
    attendance_seen = set()
    if student_ids:
        attendance_rows = db.execute(
            select(AttendanceRecord.student_user_id, AttendanceRecord.status)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(AttendanceSession.class_id == cid, or_(AttendanceSession.status == "ENDED", AttendanceSession.expires_at <= now()), AttendanceRecord.student_user_id.in_(student_ids))
        ).all()
        for student_id, status in attendance_rows:
            attendance_seen.add(student_id)
            attendance_deductions[student_id] = attendance_deductions.get(student_id, 0) + {"ABSENT": 1, "PENDING": 1, "LATE": 0.5}.get(status, 0)

    items = []
    for _, student, team_name in rows:
        homework_component = round(homework_avg[student.id] / 100 * 10, 1) if student.id in homework_avg else None
        attendance_component = max(0, 10 - attendance_deductions[student.id]) if student.id in attendance_seen else None
        routine_score = round(homework_component + attendance_component, 1) if homework_component is not None and attendance_component is not None else None
        lab_score = round(lab_avg[student.id] / 100 * 30, 1) if student.id in lab_avg else None
        capstone_score = round(capstone_avg[student.id] / 100 * 50, 1) if student.id in capstone_avg else None
        composite_score = round(routine_score + lab_score + capstone_score, 1) if routine_score is not None and lab_score is not None and capstone_score is not None else None
        items.append({
            "student_id": str(student.id), "student_no": student.login_name, "name": student.display_name,
            "team_name": team_name, "homework_component": homework_component, "attendance_component": attendance_component,
            "routine_score": routine_score, "lab_score": lab_score, "capstone_score": capstone_score,
            "composite_score": composite_score, "grade": composite_grade_letter(composite_score) if composite_score is not None else None,
        })
    return {"items": items, "total": len(items)}


@router.get("/api/v1/grades/assignments/{assignment_id}")
def grade_assignment_detail(assignment_id: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment, campaign = require_grade_assignment(db, user, assignment_id)
    rows = db.execute(
        select(Grade, User, GradeCoefficient, Team)
        .join(User, User.id == Grade.subject_user_id)
        .outerjoin(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
        .outerjoin(Team, Team.id == GradeCoefficient.team_id)
        .where(Grade.assignment_id == assignment_id)
        .order_by(Team.name, User.login_name)
    ).all()
    items = []
    for grade, person, coefficient, team_item in rows:
        changed = bool(grade.status == "PUBLISHED" and grade.draft_score is not None and grade.draft_score != grade.score)
        if grade.peer_score is None: display_status = "PENDING_REVIEW"
        elif not coefficient or coefficient.draft_value is None: display_status = "PENDING_COEFFICIENT"
        elif changed: display_status = "CHANGED"
        else: display_status = grade.status
        items.append({
            "id": str(grade.id), "user_id": str(person.id), "student_no": person.login_name, "student_name": person.display_name,
            "team_id": str(team_item.id) if team_item else None, "team_name": team_item.name if team_item else "未分组",
            "peer_score": grade.peer_score, "draft_coefficient": coefficient.draft_value if coefficient else None,
            "published_coefficient": coefficient.published_value if coefficient else None, "draft_score": grade.draft_score,
            "score": grade.score, "status": display_status, "has_unpublished_changes": changed,
        })
    coefficients = db.execute(
        select(GradeCoefficient, Team).join(Team, Team.id == GradeCoefficient.team_id)
        .where(GradeCoefficient.assignment_id == assignment_id).order_by(Team.name)
    ).all()
    groups = [{"team_id": str(team_item.id), "team_name": team_item.name, "draft_value": item.draft_value, "published_value": item.published_value, "version": item.version, "member_count": sum(row[0].coefficient_id == item.id for row in rows)} for item, team_item in coefficients]
    return {
        "assignment": {"id": str(assignment.id), "title": assignment.title, "campaign_status": campaign.status, "grades_generated_at": campaign.grades_generated_at},
        "groups": groups, "items": items, "total": len(items),
        "summary": {"publishable": sum(item["peer_score"] is not None and item["draft_score"] is not None for item in items), "pending": sum(item["peer_score"] is None for item in items), "changed": sum(item["has_unpublished_changes"] for item in items), "published": sum(item["score"] is not None for item in items)},
    }


@router.patch("/api/v1/grades/assignments/{assignment_id}/teams/{team_id}/coefficient")
def update_grade_coefficient(assignment_id: UUID, team_id: UUID, data: CoefficientIn, user: CsrfUser, db: Db):
    teacher(user); assignment, campaign = require_grade_assignment(db, user, assignment_id); require_writable_class(db, user, assignment.class_id)
    if campaign.grades_generated_at is None: raise ApiError(409, "GRADES_NOT_GENERATED", "互评结束后才能设置成绩系数")
    coefficient = db.scalar(select(GradeCoefficient).where(GradeCoefficient.assignment_id == assignment_id, GradeCoefficient.team_id == team_id).with_for_update())
    if not coefficient: raise ApiError(404, "GRADE_COEFFICIENT_NOT_FOUND", "该作业没有此小组的系数记录")
    if coefficient.version != data.version: raise ApiError(409, "GRADE_COEFFICIENT_VERSION_CONFLICT", "小组系数已被修改，请刷新后重试", {"current_version": coefficient.version})
    coefficient.draft_value, coefficient.updated_by, coefficient.version = data.coefficient, user.id, coefficient.version + 1
    grade_rows = db.scalars(select(Grade).where(Grade.coefficient_id == coefficient.id).with_for_update()).all()
    for grade in grade_rows:
        grade.draft_score = final_score(grade.peer_score, data.coefficient) if grade.peer_score is not None else None
        if grade.status != "PUBLISHED": grade.status = "DRAFT" if grade.draft_score is not None else "PENDING"
        grade.version += 1
    audit(db, user, "GRADE_COEFFICIENT_UPDATED", "assignment", str(assignment_id), {"team_id": str(team_id), "coefficient": str(data.coefficient)}); db.commit()
    return {"team_id": str(team_id), "draft_value": coefficient.draft_value, "published_value": coefficient.published_value, "version": coefficient.version}


@router.post("/api/v1/grades/assignments/{assignment_id}/publish")
def publish_assignment_grades(assignment_id: UUID, data: GradePublishIn, user: CsrfUser, db: Db):
    teacher(user); assignment, campaign = require_grade_assignment(db, user, assignment_id); require_writable_class(db, user, assignment.class_id)
    if campaign.grades_generated_at is None: raise ApiError(409, "GRADES_NOT_GENERATED", "互评结束后才能发布成绩")
    rows = db.execute(
        select(Grade, GradeCoefficient)
        .join(GradeCoefficient, GradeCoefficient.id == Grade.coefficient_id)
        .where(Grade.assignment_id == assignment_id, Grade.peer_score.is_not(None), Grade.draft_score.is_not(None))
        .with_for_update()
    ).all()
    changed = [(grade, coefficient) for grade, coefficient in rows if grade.status == "PUBLISHED" and grade.score != grade.draft_score]
    if changed and len(data.reason.strip()) < 2: raise ApiError(422, "GRADE_CHANGE_REASON_REQUIRED", "修改已发布成绩时必须填写原因")
    if not rows: raise ApiError(409, "NO_PUBLISHABLE_GRADES", "当前没有可发布的成绩")
    published = 0
    touched_coefficients = set()
    for grade, coefficient in rows:
        if grade.status == "PUBLISHED" and grade.score == grade.draft_score: continue
        if grade.status == "PUBLISHED":
            db.add(GradeRevision(grade_id=grade.id, changed_by=user.id, peer_score=grade.peer_score, coefficient=coefficient.published_value, score=grade.score, reason=data.reason.strip()))
        grade.score, grade.status, grade.version = grade.draft_score, "PUBLISHED", grade.version + 1
        touched_coefficients.add(coefficient.id)
        notify(db, grade.subject_user_id, "GRADE_PUBLISHED", f"成绩已发布：{assignment.title}")
        published += 1
    for coefficient in {item for _, item in rows if item.id in touched_coefficients}:
        coefficient.published_value = coefficient.draft_value
        coefficient.version += 1
    audit(db, user, "GRADES_PUBLISHED", "assignment", str(assignment_id), {"published": published, "reason": data.reason.strip()}); db.commit()
    pending = db.scalar(select(func.count()).select_from(Grade).where(Grade.assignment_id == assignment_id, or_(Grade.peer_score.is_(None), Grade.draft_score.is_(None)))) or 0
    return {"published": published, "pending": pending, "changed": len(changed)}


@router.get("/api/v1/grades/{gid}/revisions")
def grade_revisions(gid: UUID, user: CurrentUser, db: Db):
    teacher(user); grade = db.get(Grade, gid); assignment = db.get(Assignment, grade.assignment_id) if grade else None
    if not grade or not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "GRADE_NOT_FOUND", "成绩不存在")
    rows = db.scalars(select(GradeRevision).where(GradeRevision.grade_id == gid).order_by(GradeRevision.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "peer_score": item.peer_score, "coefficient": item.coefficient, "score": item.score, "reason": item.reason, "created_at": item.created_at} for item in rows]}
