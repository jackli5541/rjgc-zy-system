from __future__ import annotations

from fastapi import APIRouter, Header
from sqlalchemy import and_, delete, select
from typing import Annotated
from uuid import UUID, uuid4

from app import storage
from app.models import Assignment, ClassMember, FileObject, FileObjectAsset, MarkdownAsset, PeerReview, ReviewAssignment, Submission, SubmissionAnnotation, SubmissionAssessment, SubmissionDocument, SubmissionDocumentAsset, SubmissionVersion, SubmissionWorkspace, Team, TeamMember, User, VersionFile
from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, require_team, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.files import BASE64_IMAGE_PATTERN
from app.core.html import clean_html
from app.core.utils import now
from app.modules.assignments.schemas import SubmissionAssessmentIn, SubmissionFeedbackIn
from app.modules.assignments.service import annotation_json, assert_submission_update_allowed, assessment_json, assessment_payload, build_submission_grade_result, check_source_images, displayed_submission_grade_result, document_is_criteria, feedback_context, feedback_json, file_json, latest_personal_submission, markdown_asset_ids, missing_submission_grade_result, own_submission, remove_file_asset_links, save_submission_feedback, submission_grade_result, sync_document_assets

router = APIRouter()

@router.get("/api/v1/assignments/{aid}/submission")
def submission(aid: UUID, user: CurrentUser, db: Db):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    s, _ = own_submission(db, a, user)
    latest = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s else None
    files = db.scalars(select(FileObject).join(VersionFile, VersionFile.file_id == FileObject.id).where(VersionFile.version_id == latest.id)).all() if latest else []
    result = displayed_submission_grade_result(db, latest) if latest else {"final_grade": None, "grading_status": "PENDING_SUBMISSION"}
    return {"status": s.status if s else "EMPTY", "submitted_at": latest.submitted_at if latest else None, "is_late": latest.is_late if latest else False, "final_grade": result.get("final_grade"), "grading_status": result.get("grading_status"), "files": [file_json(file) for file in files]}


@router.post("/api/v1/assignments/{aid}/submission", status_code=201)
def submit(aid: UUID, user: CsrfUser, db: Db, idempotency_key: Annotated[str | None, Header()] = None):
    a = db.get(Assignment, aid)
    if not a: raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    if a.status == "CLOSED": raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止，不能继续提交")
    if a.status != "PUBLISHED": raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "可提交的作业不存在")
    require_writable_class(db, user, a.class_id)
    if a.starts_at and a.starts_at > now(): raise ApiError(409, "ASSIGNMENT_NOT_STARTED", "作业尚未开始")
    team = None
    if a.submitter_type == "INDIVIDUAL":
        db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        s = db.scalar(select(Submission).where(Submission.assignment_id == aid, Submission.owner_user_id == user.id).with_for_update())
    else:
        _, team = require_team(db, a.class_id, user)
        db.scalar(select(Team.id).where(Team.id == team.id).with_for_update())
        s = db.scalar(select(Submission).where(Submission.assignment_id == aid, Submission.owner_team_id == team.id).with_for_update())
        if team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "小组作业仅组长可正式提交")
    current = db.scalar(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.version_no == s.current_version_no)) if s and s.current_version_no else None
    if idempotency_key and current and current.idempotency_key == idempotency_key:
        return {"id": str(s.id), "submitted_at": current.submitted_at, "is_late": current.is_late}
    assert_submission_update_allowed(db, s, current) if s else None
    can_update_low_grade = bool(current and submission_grade_result(db, current).get("final_grade") in {"C", "D", "E"})
    if a.due_at < now() and not a.allow_late and not can_update_low_grade:
        raise ApiError(409, "ASSIGNMENT_CLOSED", "作业已截止且不允许迟交")
    file_scope = FileObject.owner_id == user.id if not team else FileObject.team_id == team.id
    workspace = db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_user_id == user.id)) if not team else db.scalar(select(SubmissionWorkspace).where(SubmissionWorkspace.assignment_id == aid, SubmissionWorkspace.owner_team_id == team.id))
    snapshot_keys = []
    try:
        if workspace:
            documents = [document for document in db.scalars(select(SubmissionDocument).where(SubmissionDocument.workspace_id == workspace.id).order_by(SubmissionDocument.sort_order, SubmissionDocument.created_at)).all() if not document_is_criteria(db, document)]
            if not documents: raise ApiError(422, "SUBMISSION_DOCUMENTS_REQUIRED", "在线作业中至少需要一份 Markdown 文档")
            for document in documents:
                check_source_images(db, workspace, document, user)
            empty = next((document for document in documents if not document.markdown_content.strip()), None)
            if empty: raise ApiError(422, "SUBMISSION_DOCUMENT_EMPTY", f"文档 {empty.name} 不能为空")
            if any(BASE64_IMAGE_PATTERN.search(document.markdown_content) for document in documents):
                raise ApiError(422, "MARKDOWN_BASE64_IMAGE_FORBIDDEN", "作业中仍有 Base64 图片，请重新插入后再提交")
            db.execute(FileObject.__table__.update().where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == True, file_scope).values(active=False))  # noqa: E712
            for document in documents:
                asset_ids = markdown_asset_ids(document.markdown_content)
                linked_ids = set(db.scalars(select(SubmissionDocumentAsset.asset_id).where(SubmissionDocumentAsset.document_id == document.id)).all())
                if asset_ids != linked_ids:
                    asset_ids = sync_document_assets(db, a, workspace, document, document.markdown_content)
                assets = db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(asset_ids))).all() if asset_ids else []
                if any(not storage.object_exists(asset.storage_path) for asset in assets):
                    raise ApiError(409, "MARKDOWN_ASSET_MISSING", f"文档 {document.name} 中有图片存储不可用")
                content = document.markdown_content.encode("utf-8")
                fid = uuid4(); relative = f"{aid}/{fid.hex}.md"
                storage.put_bytes(relative, content)
                snapshot_keys.append(relative)
                db.add(FileObject(id=fid, owner_id=user.id, assignment_id=aid, team_id=team.id if team else None, purpose="SUBMISSION", storage_path=relative, original_name=document.name, size_bytes=len(content), detected_mime="text/markdown", preview_status="READY"))
                for asset_id in asset_ids:
                    db.add(FileObjectAsset(file_id=fid, asset_id=asset_id))
            db.flush()
    except Exception:
        db.rollback()
        for key in snapshot_keys:
            storage.delete_object(key)
        raise
    try:
        files = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == True, file_scope).order_by(FileObject.created_at)).all()  # noqa: E712
        if not files: raise ApiError(422, "SUBMISSION_FILES_REQUIRED", "请先上传作业附件")
        if not s: s = Submission(assignment_id=aid, owner_user_id=user.id if not team else None, owner_team_id=team.id if team else None); db.add(s); db.flush()
        snapshot = {}
        if team:
            rows = db.execute(select(TeamMember, User).join(User).where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE").order_by(User.login_name)).all()
            snapshot = {"members": [{"id": str(person.id), "student_no": person.login_name, "name": person.display_name, "role": member.role} for member, person in rows]}
        submitted_at = now()
        s.current_version_no = (current.version_no + 1) if current else 1
        was_peer_reviewed = bool(current and db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == current.id, SubmissionAssessment.kind == "PEER", SubmissionAssessment.status == "PUBLISHED").limit(1)))
        resubmission_grade_cap = "B" if was_peer_reviewed else None
        v = SubmissionVersion(submission_id=s.id, version_no=s.current_version_no, submitted_by=user.id, submitted_at=submitted_at, member_snapshot=snapshot, is_late=a.due_at < submitted_at, idempotency_key=idempotency_key, grade_cap=resubmission_grade_cap)
        db.add(v); db.flush()
        old_versions = db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id == s.id, SubmissionVersion.id != v.id)).all()
        for old in old_versions:
            frozen = db.scalar(select(ReviewAssignment.id).where(ReviewAssignment.submission_version_id == old.id).limit(1)) or db.scalar(select(PeerReview.id).where(PeerReview.submission_version_id == old.id).limit(1)) or db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == old.id).limit(1))
            if not frozen:
                db.execute(delete(VersionFile).where(VersionFile.version_id == old.id))
                db.delete(old)
        s.status = "SUBMITTED"
        for f in files: db.add(VersionFile(version_id=v.id, file_id=f.id))
        db.flush()
        stale_keys = []
        inactive = db.scalars(select(FileObject).where(FileObject.assignment_id == aid, FileObject.purpose == "SUBMISSION", FileObject.active == False, file_scope)).all()  # noqa: E712
        for file in inactive:
            if not db.scalar(select(VersionFile.file_id).where(VersionFile.file_id == file.id).limit(1)):
                stale_keys.append(file.storage_path)
                remove_file_asset_links(db, [file.id])
                db.delete(file)
        audit(db, user, "SUBMISSION_CREATED", "submission", str(s.id))
        db.commit()
    except Exception:
        db.rollback()
        for key in snapshot_keys:
            storage.delete_object(key)
        raise
    for key in stale_keys:
        storage.delete_object(key)
    return {"id": str(s.id), "submitted_at": v.submitted_at, "is_late": v.is_late}


@router.post("/api/v1/assignments/{aid}/submissions/{student_id}/grade", status_code=201)
def save_teacher_submission_assessment(aid: UUID, student_id: UUID, data: SubmissionAssessmentIn, user: CsrfUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    submitted = latest_personal_submission(db, aid, student_id)
    if not submitted: raise ApiError(409, "SUBMISSION_REQUIRED", "该学生尚未提交作业")
    _, version = submitted
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    updating = item is not None
    if item:
        item.grade, item.comment, item.status, item.published_at = data.grade, clean_html(data.comment), "PUBLISHED", now()
        item.version += 1
    else:
        item = SubmissionAssessment(assignment_id=aid, submission_version_id=version.id, evaluator_id=user.id, subject_user_id=student_id, kind="TEACHER", grade=data.grade, comment=clean_html(data.comment), status="PUBLISHED", published_at=now())
        db.add(item)
    db.flush(); audit(db, user, "TEACHER_ASSESSMENT_UPDATED" if updating else "TEACHER_ASSESSMENT_SUBMITTED", "submission_assessment", str(item.id), {"grade": data.grade, "subject_user_id": str(student_id)}); db.commit()
    return {**assessment_json(db, item), "updated": updating, "result": submission_grade_result(db, version)}


@router.delete("/api/v1/assignments/{aid}/submissions/{student_id}/grade")
def delete_teacher_submission_assessment(aid: UUID, student_id: UUID, user: CsrfUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or assignment.submitter_type != "INDIVIDUAL" or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    require_writable_class(db, user, assignment.class_id)
    submitted = latest_personal_submission(db, aid, student_id)
    if not submitted: raise ApiError(409, "SUBMISSION_REQUIRED", "该学生尚未提交作业")
    _, version = submitted
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    if item:
        item_id = str(item.id); db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == item.id)); db.delete(item); db.flush(); audit(db, user, "TEACHER_ASSESSMENT_CLEARED", "submission_assessment", item_id)
    result = submission_grade_result(db, version); db.commit()
    return result


@router.get("/api/v1/submission-versions/{version_id}/feedback")
def get_submission_feedback(version_id: UUID, user: CurrentUser, db: Db):
    version, _, _ = feedback_context(db, version_id, user)
    query = select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.kind == "TEACHER")
    if user.role == "TEACHER": query = query.where(SubmissionAssessment.evaluator_id == user.id)
    else: query = query.where(SubmissionAssessment.status == "PUBLISHED")
    item = db.scalar(query.order_by(SubmissionAssessment.updated_at.desc()))
    return feedback_json(db, item, user.role == "TEACHER")


@router.put("/api/v1/submission-versions/{version_id}/feedback/draft")
def save_submission_feedback_draft(version_id: UUID, data: SubmissionFeedbackIn, user: CsrfUser, db: Db):
    return save_submission_feedback(version_id, data, user, db, False)


@router.post("/api/v1/submission-versions/{version_id}/feedback/publish")
def publish_submission_feedback(version_id: UUID, data: SubmissionFeedbackIn, user: CsrfUser, db: Db):
    return save_submission_feedback(version_id, data, user, db, True)


@router.delete("/api/v1/submission-versions/{version_id}/feedback")
def delete_submission_feedback(version_id: UUID, user: CsrfUser, db: Db):
    teacher(user)
    version, _, assignment = feedback_context(db, version_id, user)
    require_writable_class(db, user, assignment.class_id)
    item = db.scalar(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.evaluator_id == user.id, SubmissionAssessment.kind == "TEACHER"))
    if item:
        item_id = str(item.id); db.execute(delete(SubmissionAnnotation).where(SubmissionAnnotation.assessment_id == item.id)); db.delete(item); db.flush(); audit(db, user, "TEACHER_ASSESSMENT_CLEARED", "submission_assessment", item_id)
    result = submission_grade_result(db, version); db.commit()
    return result


@router.get("/api/v1/assignments/{aid}/submissions")
def submission_board(aid: UUID, user: CurrentUser, db: Db):
    teacher(user); assignment = db.get(Assignment, aid)
    if not assignment or not user_class(db, user, assignment.class_id): raise ApiError(404, "ASSIGNMENT_NOT_FOUND", "作业不存在")
    rows = list(db.scalars(select(Submission).where(Submission.assignment_id == aid)).all())
    by_owner = {str(row.owner_user_id or row.owner_team_id): row for row in rows}
    submissions_by_id = {row.id: row for row in rows}
    if assignment.submitter_type == "INDIVIDUAL":
        owner_rows = db.execute(
            select(ClassMember, User, Team)
            .join(User, User.id == ClassMember.user_id)
            .outerjoin(TeamMember, and_(
                TeamMember.class_id == ClassMember.class_id,
                TeamMember.user_id == ClassMember.user_id,
                TeamMember.status == "ACTIVE",
            ))
            .outerjoin(Team, and_(Team.id == TeamMember.team_id, Team.status == "ACTIVE"))
            .where(ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")
            .order_by(User.login_name)
        ).all()
        owners = [
            (member.user_id, person.display_name, person.login_name, team.id if team else None, team.name if team else None)
            for member, person, team in owner_rows
        ]
    else:
        owners = [(team.id, team.name, None, team.id, team.name) for team in db.scalars(select(Team).where(Team.class_id == assignment.class_id, Team.status == "ACTIVE").order_by(Team.name)).all()]

    versions = list(db.scalars(
        select(SubmissionVersion)
        .join(Submission, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(Submission.assignment_id == aid)
    ).all()) if rows else []
    versions_by_submission = {version.submission_id: version for version in versions}
    submitted_versions = [
        version for version in versions
        if submissions_by_id[version.submission_id].status == "SUBMITTED"
    ]
    submitted_version_ids = [version.id for version in submitted_versions]

    files_by_version: dict[UUID, list[FileObject]] = {}
    if submitted_version_ids:
        for version_id, file in db.execute(
            select(VersionFile.version_id, FileObject)
            .join(FileObject, FileObject.id == VersionFile.file_id)
            .where(VersionFile.version_id.in_(submitted_version_ids))
        ):
            files_by_version.setdefault(version_id, []).append(file)

    assessments_by_version: dict[UUID, list[SubmissionAssessment]] = {}
    assessments = list(db.scalars(
        select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id.in_(submitted_version_ids))
    ).all()) if submitted_version_ids else []
    for assessment in assessments:
        assessments_by_version.setdefault(assessment.submission_version_id, []).append(assessment)

    evaluator_names = dict(db.execute(
        select(User.id, User.display_name).where(User.id.in_({item.evaluator_id for item in assessments}))
    ).all()) if assessments else {}
    annotations_by_assessment: dict[UUID, list[dict]] = {}
    if assessments:
        assessment_ids = [item.id for item in assessments]
        annotations = db.scalars(
            select(SubmissionAnnotation)
            .where(SubmissionAnnotation.assessment_id.in_(assessment_ids))
            .order_by(SubmissionAnnotation.position, SubmissionAnnotation.created_at)
        ).all()
        for annotation in annotations:
            annotations_by_assessment.setdefault(annotation.assessment_id, []).append(annotation_json(annotation))

    def serialize_assessment(item: SubmissionAssessment) -> dict:
        return assessment_payload(item, evaluator_names[item.evaluator_id], annotations_by_assessment.get(item.id, []))

    items = []
    for owner_id, owner_name, student_no, team_id, team_name in owners:
        submission = by_owner.get(str(owner_id))
        latest = versions_by_submission.get(submission.id) if submission else None
        files = files_by_version.get(latest.id, []) if latest and submission.status == "SUBMITTED" else []
        grade_result = build_submission_grade_result(assessments_by_version.get(latest.id, []), serialize_assessment) if latest and submission.status == "SUBMITTED" else missing_submission_grade_result(assignment)
        if latest and submission.status == "SUBMITTED" and not grade_result.get("final_grade") and latest.version_no > 1:
            grade_result = displayed_submission_grade_result(db, latest, grade_result)
        items.append({"id": str(submission.id) if submission else str(owner_id), "submission_version_id": str(latest.id) if latest and submission.status == "SUBMITTED" else None, "submission_version_no": latest.version_no if latest and submission.status == "SUBMITTED" else None, "grade_cap": latest.grade_cap if latest and submission.status == "SUBMITTED" else None, "user_id": str(owner_id) if assignment.submitter_type == "INDIVIDUAL" else None, "owner": owner_name, "student_no": student_no, "team_id": str(team_id) if team_id else None, "team_name": team_name, "status": submission.status if submission else "NOT_SUBMITTED", "submitted_at": latest.submitted_at if latest and submission.status == "SUBMITTED" else None, "is_late": latest.is_late if latest and submission.status == "SUBMITTED" else False, "member_snapshot": latest.member_snapshot if latest else {}, "files": [file_json(file) for file in files], **grade_result})
    return {"items": items, "total": len(items)}
