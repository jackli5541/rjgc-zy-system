"""批改结果导入：校验、预览分组、确认写入。写入沿用平台现有的教师评价与互评二次点评路径。"""
from __future__ import annotations

import html
from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from app.core.audit import audit, notify
from app.core.errors import ApiError
from app.core.html import clean_html, html_to_text
from app.core.utils import now
from app.models import (AgentImportBatch, AiGradingDraft, Assignment, ClassMember, PeerAssessmentFeedback, Submission,
                        SubmissionAssessment, SubmissionVersion, User)
from app.modules.agent_access import excel
from app.modules.assignments.service import publish_peer_assessment_feedbacks, upsert_teacher_assessment

GRADES = {"A", "B", "C", "D", "E"}
MAX_COMMENT = 2000
MAX_REASON = 20000


def text_to_html(value: str) -> str:
    lines = [line.strip() for line in value.replace("\r", "").split("\n") if line.strip()]
    return "".join(f"<p>{html.escape(line)}</p>" for line in lines)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        return None


def _latest_map(db: Session, assignment: Assignment) -> dict[UUID, tuple[SubmissionVersion, User]]:
    rows = db.execute(
        select(SubmissionVersion, User)
        .join(Submission, and_(Submission.id == SubmissionVersion.submission_id, SubmissionVersion.version_no == Submission.current_version_no))
        .join(User, User.id == Submission.owner_user_id)
        .join(ClassMember, and_(ClassMember.user_id == User.id, ClassMember.class_id == assignment.class_id, ClassMember.status == "ACTIVE"))
        .where(Submission.assignment_id == assignment.id, Submission.status == "SUBMITTED", Submission.owner_user_id.is_not(None))
    ).all()
    return {version.id: (version, student) for version, student in rows}


def validate(db: Session, teacher: User, assignment: Assignment, parsed: dict) -> dict:
    """逐行校验。不写库，返回预览报告；确认时重新校验一遍，防止预览后数据变化。"""
    latest = _latest_map(db, assignment)
    meta_assignment = parsed["meta"].get("assignment_id")
    if meta_assignment and meta_assignment != str(assignment.id):
        raise ApiError(422, "IMPORT_ASSIGNMENT_MISMATCH", "这份 Excel 不是该作业的模板，请核对作业后重新下载")

    version_ids = list(latest)
    existing_teacher = {
        item.submission_version_id: item
        for item in db.scalars(select(SubmissionAssessment).where(
            SubmissionAssessment.submission_version_id.in_(version_ids), SubmissionAssessment.kind == "TEACHER", SubmissionAssessment.status == "PUBLISHED"))
    } if version_ids else {}
    ai_drafts = set(db.scalars(select(AiGradingDraft.submission_version_id).where(
        AiGradingDraft.submission_version_id.in_(version_ids), AiGradingDraft.teacher_id == teacher.id,
        AiGradingDraft.status.in_(["READY", "PROCESSING"])))) if version_ids else set()

    grades, seen = [], set()
    for row in parsed["grades"]:
        errors, vid = [], _uuid(row.get("version_id", ""))
        entry = {"row": row["_row"], "version_id": row.get("version_id", ""), "student_no": row.get("学号", ""), "name": row.get("姓名", ""),
                 "grade": row.get("教师等级", "").upper(), "comment": row.get("作业点评", ""), "status": "OK", "errors": errors,
                 "ai_draft": False, "existing_grade": None, "needs_overwrite": False, "feedback_count": 0}
        if not entry["grade"] and not entry["comment"]:
            entry["status"] = "SKIPPED"
            entry["errors"] = ["未填写等级和点评，视为未完成，已跳过"]
            grades.append(entry)
            continue
        row_assignment = row.get("作业ID", "")
        if row_assignment and row_assignment != str(assignment.id):
            errors.append("作业ID与所选作业不一致")
        if vid is None:
            errors.append("version_id 格式不正确")
        elif vid in seen:
            errors.append("version_id 重复出现")
        elif vid not in latest:
            stale = db.scalar(select(SubmissionVersion.id).join(Submission, Submission.id == SubmissionVersion.submission_id)
                              .where(SubmissionVersion.id == vid, Submission.assignment_id == assignment.id))
            errors.append("该学生已重新提交，这个版本不是最新提交，请重新批改" if stale else "version_id 不属于该作业的有效个人提交")
        if vid is not None:
            seen.add(vid)
        if entry["grade"] not in GRADES:
            errors.append("教师等级必须是 A–E")
        if not entry["comment"]:
            errors.append("作业点评不能为空")
        elif len(entry["comment"]) > MAX_COMMENT:
            errors.append(f"作业点评超过 {MAX_COMMENT} 字")
        if vid in latest:
            version, student = latest[vid]
            entry["student_id"] = str(student.id)
            entry["student_no"], entry["name"] = student.login_name, student.display_name
            entry["ai_draft"] = vid in ai_drafts
            if vid in existing_teacher:
                entry["existing_grade"] = existing_teacher[vid].grade
                entry["needs_overwrite"] = True
        if errors:
            entry["status"] = "ERROR"
        grades.append(entry)
    by_version = {item["version_id"]: item for item in grades if item["status"] == "OK"}

    feedbacks = []
    for row in parsed["feedbacks"]:
        errors = []
        entry = {"row": row["_row"], "version_id": row.get("version_id", ""), "assessment_id": row.get("assessment_id", ""), "reviewer": row.get("互评者", ""),
                 "target_type": excel.target_from_text(row.get("针对", "")), "category": excel.category_from_text(row.get("二次点评类别", "")),
                 "reason": row.get("二次点评内容", ""), "status": "OK", "errors": errors}
        if not entry["category"] and not entry["reason"]:
            continue
        aid = _uuid(row.get("assessment_id", ""))
        if entry["version_id"] not in by_version:
            errors.append("对应学生的批改行无效或未填写，二次点评不导入")
        if aid is None:
            errors.append("assessment_id 格式不正确")
        else:
            peer = db.get(SubmissionAssessment, aid)
            if not peer or peer.kind != "PEER" or peer.status != "PUBLISHED" or str(peer.submission_version_id) != entry["version_id"]:
                errors.append("assessment_id 不是该提交收到的有效互评")
        if not entry["target_type"]:
            errors.append("「针对」只能填 评分 或 总体评语")
        if not entry["category"]:
            errors.append("二次点评类别无法识别")
        if not entry["reason"]:
            errors.append("二次点评内容不能为空")
        elif len(entry["reason"]) > MAX_REASON:
            errors.append("二次点评内容过长")
        if errors:
            entry["status"] = "ERROR"
        elif entry["version_id"] in by_version:
            by_version[entry["version_id"]]["feedback_count"] += 1
        feedbacks.append(entry)
    return {"assignment_id": str(assignment.id), "grades": grades, "feedbacks": feedbacks, "summary": summarize(grades, feedbacks)}


def summarize(grades: list[dict], feedbacks: list[dict]) -> dict:
    ok = [item for item in grades if item["status"] == "OK"]
    return {
        "total": len(grades), "ok": len(ok), "error": sum(item["status"] == "ERROR" for item in grades),
        "skipped": sum(item["status"] == "SKIPPED" for item in grades),
        "ai_draft": sum(item["ai_draft"] for item in ok), "needs_overwrite": sum(item["needs_overwrite"] for item in ok),
        "feedback_ok": sum(item["status"] == "OK" for item in feedbacks), "feedback_error": sum(item["status"] == "ERROR" for item in feedbacks),
    }


def create_preview(db: Session, teacher: User, assignment: Assignment, file_name: str, content: bytes) -> dict:
    try:
        parsed = excel.parse_workbook(content)
    except ValueError as exc:
        raise ApiError(422, "IMPORT_FILE_INVALID", str(exc))
    report = validate(db, teacher, assignment, parsed)
    batch = AgentImportBatch(teacher_id=teacher.id, assignment_id=assignment.id, file_name=file_name[:255], status="PREVIEW",
                             payload={"grades": parsed["grades"], "feedbacks": parsed["feedbacks"], "meta": parsed["meta"]}, summary=report["summary"])
    db.add(batch)
    db.flush()
    report["batch_id"] = str(batch.id)
    return report


def _supersede_ai_drafts(db: Session, version_id: UUID, teacher_id: UUID) -> int:
    drafts = db.scalars(select(AiGradingDraft).where(AiGradingDraft.submission_version_id == version_id, AiGradingDraft.teacher_id == teacher_id,
                                                      AiGradingDraft.status.in_(["READY", "PROCESSING"])).order_by(AiGradingDraft.created_at.desc())).all()
    if not drafts:
        return 0
    # (版本, 教师, 状态) 唯一：只保留最新的一份作为"被替代"，其余旧记录清理。
    db.execute(delete(AiGradingDraft).where(AiGradingDraft.submission_version_id == version_id, AiGradingDraft.teacher_id == teacher_id,
                                            AiGradingDraft.status == "SUPERSEDED"))
    for extra in drafts[1:]:
        db.delete(extra)
    drafts[0].status = "SUPERSEDED"
    db.flush()
    return len(drafts)


def confirm(db: Session, teacher: User, batch: AgentImportBatch, assignment: Assignment, overwrite_version_ids: set[str]) -> dict:
    report = validate(db, teacher, assignment, {"grades": batch.payload["grades"], "feedbacks": batch.payload["feedbacks"], "meta": batch.payload.get("meta", {})})
    feedback_by_version: dict[str, list[dict]] = {}
    for item in report["feedbacks"]:
        if item["status"] == "OK":
            feedback_by_version.setdefault(item["version_id"], []).append(item)
    latest = _latest_map(db, assignment)
    imported, failed, skipped = [], [], []
    for item in report["grades"]:
        label = {"row": item["row"], "student_no": item["student_no"], "name": item["name"]}
        if item["status"] == "SKIPPED":
            skipped.append({**label, "reason": "未完成"})
            continue
        if item["status"] == "ERROR":
            failed.append({**label, "reason": "；".join(item["errors"])})
            continue
        if item["needs_overwrite"] and item["version_id"] not in overwrite_version_ids:
            skipped.append({**label, "reason": "已有教师评价，未勾选覆盖"})
            continue
        version, student = latest[UUID(item["version_id"])]
        try:
            with db.begin_nested():
                assessment, updating = upsert_teacher_assessment(db, teacher, assignment.id, student.id, version, item["grade"], text_to_html(item["comment"]))
                superseded = _supersede_ai_drafts(db, version.id, teacher.id)
                created = 0
                for fb in feedback_by_version.get(item["version_id"], []):
                    reason = clean_html(text_to_html(fb["reason"]))
                    duplicate = db.scalar(select(PeerAssessmentFeedback.id).where(
                        PeerAssessmentFeedback.assessment_id == UUID(fb["assessment_id"]), PeerAssessmentFeedback.teacher_id == teacher.id,
                        PeerAssessmentFeedback.target_type == fb["target_type"], PeerAssessmentFeedback.reason == reason, PeerAssessmentFeedback.revoked_at.is_(None)).limit(1))
                    if duplicate:
                        continue
                    db.add(PeerAssessmentFeedback(assessment_id=UUID(fb["assessment_id"]), target_type=fb["target_type"], category=fb["category"], reason=reason, teacher_id=teacher.id))
                    created += 1
                db.flush()
                # 站内信只提示已评阅，不带等级与评语（学生点开作业详情查看）
                notify(db, student.id, "TEACHER_ASSESSMENT",
                       f"{'教师更新了对' if updating else '教师已评阅：'}《{assignment.title}》{'的评阅' if updating else ''}",
                       "assignment", str(assignment.id))
                publish_peer_assessment_feedbacks(db, version.id, teacher)
                audit(db, teacher, "TEACHER_ASSESSMENT_UPDATED" if updating else "TEACHER_ASSESSMENT_SUBMITTED", "submission_assessment", str(assessment.id),
                      {"grade": item["grade"], "subject_user_id": str(student.id), "source": "agent_import"})
            imported.append({**label, "grade": item["grade"], "overwritten": updating, "ai_draft_superseded": bool(superseded), "feedbacks": created})
        except Exception as exc:  # 单个学生失败不影响其他人
            failed.append({**label, "reason": f"写入失败：{type(exc).__name__}"})
    result = {"imported": imported, "failed": failed, "skipped": skipped,
              "summary": {"imported": len(imported), "failed": len(failed), "skipped": len(skipped)}}
    batch.status, batch.confirmed_at, batch.summary = "CONFIRMED", now(), result["summary"]
    audit(db, teacher, "AGENT_RESULT_IMPORTED", "assignment", str(assignment.id), {"batch_id": str(batch.id), "file_name": batch.file_name, **result["summary"]})
    return result


def plain_peer_text(value: str) -> str:
    return html_to_text(value or "")


def template_bytes(db: Session, assignment: Assignment) -> bytes:
    latest = _latest_map(db, assignment)
    ordered = sorted(latest.values(), key=lambda pair: pair[1].login_name)
    grade_rows, feedback_rows = [], []
    for version, student in ordered:
        peers = db.scalars(select(SubmissionAssessment).where(SubmissionAssessment.submission_version_id == version.id, SubmissionAssessment.kind == "PEER",
                                                              SubmissionAssessment.status == "PUBLISHED").order_by(SubmissionAssessment.created_at, SubmissionAssessment.id)).all()
        submitted = version.submitted_at.strftime("%Y-%m-%d %H:%M") if version.submitted_at else ""
        grade_rows.append([str(assignment.id), str(version.id), student.login_name, student.display_name, submitted, "", "", f"{len(peers)} 条互评", ""])
        for index, peer in enumerate(peers, 1):
            reviewer = db.get(User, peer.evaluator_id)
            feedback_rows.append([str(version.id), str(peer.id), reviewer.display_name if reviewer else f"互评者{index}", peer.grade, plain_peer_text(peer.comment), "", "", ""])
    return excel.build_template(str(assignment.id), assignment.title, grade_rows, feedback_rows)
