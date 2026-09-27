from __future__ import annotations

import io
import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Response
from openpyxl import Workbook
from sqlalchemy import delete, func, select

from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, require_class, require_writable_class, teacher
from app.core.errors import ApiError
from app.core.utils import content_disposition, now
from app.models import AttendanceRecord, AttendanceSession, ClassMember, TeachingClass, User
from app.modules.attendance.schemas import AttendanceCheckIn, AttendanceCorrection, AttendanceSessionIn
from app.modules.attendance.service import STATUS_LABELS, aware, close_expired, code_valid, finish_session, record_json, roster_records, session_json
from app.modules.grades.service import export_cell

router = APIRouter()


def xlsx_cell(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def teacher_session(db: Db, user: CurrentUser, session_id: UUID, lock: bool = False) -> AttendanceSession:
    teacher(user)
    query = select(AttendanceSession).where(AttendanceSession.id == session_id)
    session = db.scalar(query.with_for_update() if lock else query)
    if not session:
        raise ApiError(404, "ATTENDANCE_NOT_FOUND", "考勤场次不存在")
    require_class(db, user, session.class_id)
    return session


@router.get("/api/v1/classes/{cid}/attendance-sessions")
def list_sessions(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); require_class(db, user, cid)
    if close_expired(db, cid, now()): db.commit()
    sessions = db.scalars(select(AttendanceSession).where(AttendanceSession.class_id == cid).order_by(AttendanceSession.started_at.desc())).all()
    if not sessions: return {"items": []}
    counts = db.execute(
        select(AttendanceRecord.session_id, AttendanceRecord.status, func.count())
        .where(AttendanceRecord.session_id.in_([item.id for item in sessions]))
        .group_by(AttendanceRecord.session_id, AttendanceRecord.status)
    ).all()
    by_session = {item.id: {"total": 0, "present": 0, "late": 0, "absent": 0, "pending": 0, "leave": 0} for item in sessions}
    for sid, status, count in counts:
        by_session[sid]["total"] += count
        by_session[sid][status.lower()] = count
    return {"items": [{**session_json(item), **by_session[item.id]} for item in sessions]}


@router.post("/api/v1/classes/{cid}/attendance-sessions", status_code=201)
def create_session(cid: UUID, data: AttendanceSessionIn, user: CsrfUser, db: Db):
    teacher(user)
    course = db.scalar(select(TeachingClass).where(TeachingClass.id == cid, TeachingClass.teacher_id == user.id).with_for_update())
    if not course: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可访问的教学班")
    if course.status != "ACTIVE": raise ApiError(409, "CLASS_ARCHIVED", "教学班已归档")
    at = now()
    close_expired(db, cid, at)
    if db.scalar(select(AttendanceSession.id).where(AttendanceSession.class_id == cid, AttendanceSession.status == "ACTIVE")):
        raise ApiError(409, "ATTENDANCE_ACTIVE", "当前教学班已有进行中或待开始的考勤")
    title = data.title.strip()
    if not title: raise ApiError(422, "TITLE_REQUIRED", "请填写考勤标题")
    if data.started_at is not None and data.started_at.utcoffset() is None:
        raise ApiError(422, "ATTENDANCE_TIMEZONE_REQUIRED", "开始时间必须包含时区")
    starts_at = aware(data.started_at) if data.started_at else at
    if starts_at < at - timedelta(minutes=1):
        raise ApiError(422, "ATTENDANCE_START_PAST", "开始时间不能早于当前时间")
    starts_at = max(starts_at, at)
    people = db.execute(
        select(ClassMember, User).join(User, User.id == ClassMember.user_id)
        .where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")
    ).all()
    if not people: raise ApiError(409, "ROSTER_EMPTY", "当前教学班没有学生")
    session = AttendanceSession(class_id=cid, title=title, code_secret=secrets.token_bytes(32), started_at=starts_at, expires_at=starts_at + timedelta(minutes=data.duration_minutes), created_by=user.id)
    db.add(session); db.flush()
    records = [AttendanceRecord(session_id=session.id, student_user_id=person.id, student_no=person.login_name, student_name=person.display_name) for _, person in people]
    db.add_all(records)
    audit(db, user, "ATTENDANCE_STARTED", "attendance_session", str(session.id), {"class_id": str(cid), "title": title, "started_at": starts_at.isoformat()})
    db.commit()
    return session_json(session, records, at, include_code=True)


@router.get("/api/v1/attendance-sessions/{sid}")
def session_detail(sid: UUID, user: CurrentUser, db: Db):
    session = teacher_session(db, user, sid)
    if close_expired(db, session.class_id, now()): db.commit()
    records = roster_records(db, session)
    return {**session_json(session, records, include_code=True), "records": [record_json(item) for item in records]}


@router.get("/api/v1/attendance-sessions/{sid}/code")
def display_code(sid: UUID, user: CurrentUser, db: Db):
    session = teacher_session(db, user, sid)
    if close_expired(db, session.class_id, now()): db.commit()
    return session_json(session, include_code=True)


@router.post("/api/v1/attendance-sessions/{sid}/end")
def end_session(sid: UUID, user: CsrfUser, db: Db):
    session = teacher_session(db, user, sid, lock=True)
    require_writable_class(db, user, session.class_id)
    if session.status == "ACTIVE":
        finish_session(db, session, now(), user=user)
        db.commit()
    return session_json(session)


@router.delete("/api/v1/attendance-sessions/{sid}", status_code=204)
def delete_session(sid: UUID, user: CsrfUser, db: Db):
    session = teacher_session(db, user, sid, lock=True)
    require_writable_class(db, user, session.class_id)
    audit(db, user, "ATTENDANCE_DELETED", "attendance_session", str(sid), {"class_id": str(session.class_id), "title": session.title, "status": session.status})
    db.execute(delete(AttendanceRecord).where(AttendanceRecord.session_id == sid))
    db.delete(session)
    db.commit()
    return Response(status_code=204)


@router.put("/api/v1/attendance-sessions/{sid}/records/{student_id}")
def correct_record(sid: UUID, student_id: UUID, data: AttendanceCorrection, user: CsrfUser, db: Db):
    session = teacher_session(db, user, sid)
    require_writable_class(db, user, session.class_id)
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == sid, AttendanceRecord.student_user_id == student_id).with_for_update())
    if not record: raise ApiError(404, "ATTENDANCE_RECORD_NOT_FOUND", "学生不在本次考勤名单")
    previous = {"status": record.status, "note": record.note}
    record.status = data.status
    record.note = data.note.strip() if data.note else None
    record.source = "TEACHER"
    record.updated_by = user.id
    record.checked_in_at = (record.checked_in_at or now()) if data.status in {"PRESENT", "LATE"} else None
    audit(db, user, "ATTENDANCE_CORRECTED", "attendance_record", str(record.id), {"class_id": str(session.class_id), "session_id": str(sid), "before": previous, "after": {"status": data.status, "note": record.note}, "student_id": str(student_id)})
    db.commit()
    return record_json(record)


@router.get("/api/v1/classes/{cid}/attendance/current")
def student_current(cid: UUID, user: CurrentUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可查看自己的考勤")
    require_class(db, user, cid)
    if close_expired(db, cid, now()): db.commit()
    sessions = db.scalars(select(AttendanceSession).where(AttendanceSession.class_id == cid).order_by(AttendanceSession.started_at.desc()).limit(10)).all()
    if not sessions: return {"active": None, "recent": []}
    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id.in_([item.id for item in sessions]), AttendanceRecord.student_user_id == user.id)).all()
    by_session = {item.session_id: item for item in records}
    for item in sessions:
        record = by_session.get(item.id)
        if item.status == "ACTIVE" and record and record.status == "ABSENT" and record.source is None:
            record.status = "PENDING"
    if db.dirty: db.commit()
    recent = [{**session_json(item), "record": record_json(by_session[item.id])} for item in sessions if item.id in by_session]
    return {"active": next((item for item in recent if item["status"] == "ACTIVE"), None), "recent": recent}


@router.post("/api/v1/attendance-sessions/{sid}/check-in")
def check_in(sid: UUID, data: AttendanceCheckIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可签到")
    at = now()
    # A transaction-held shared lock lets students sign in concurrently while end/delete waits.
    session = db.scalar(select(AttendanceSession).where(AttendanceSession.id == sid).with_hint(AttendanceSession, "WITH (HOLDLOCK, ROWLOCK)", dialect_name="mssql"))
    if not session: raise ApiError(404, "ATTENDANCE_NOT_FOUND", "考勤场次不存在")
    require_writable_class(db, user, session.class_id)
    if session.status != "ACTIVE" or aware(session.expires_at) <= at:
        if close_expired(db, session.class_id, at): db.commit()
        raise ApiError(409, "ATTENDANCE_ENDED", "本次考勤已结束")
    if aware(session.started_at) > at:
        raise ApiError(409, "ATTENDANCE_NOT_STARTED", "本次考勤尚未开始")
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == sid, AttendanceRecord.student_user_id == user.id).with_for_update())
    if not record: raise ApiError(403, "NOT_IN_ATTENDANCE_ROSTER", "你不在本次考勤名单")
    if record.status == "ABSENT" and record.source is None:
        record.status = "PENDING"
    if record.source == "TEACHER" and record.status == "ABSENT":
        raise ApiError(409, "ATTENDANCE_LOCKED", "教师已确认本次记录，请联系教师")
    if record.status != "PENDING": return record_json(record)
    if record.failed_window_at is None or aware(record.failed_window_at) <= at - timedelta(minutes=1):
        record.failed_window_at = at
        record.failed_attempts = 0
    if record.failed_attempts >= 5:
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "输入次数过多，请稍后重试")
    if not code_valid(session, data.code, at):
        record.failed_attempts += 1
        db.commit()
        raise ApiError(422, "ATTENDANCE_CODE_INVALID", "考勤码不正确或已更新")
    record.status = "PRESENT"
    record.checked_in_at = at
    record.source = "CODE"
    record.failed_attempts = 0
    audit(db, user, "ATTENDANCE_CHECKED_IN", "attendance_record", str(record.id), {"class_id": str(session.class_id), "session_id": str(session.id), "student_id": str(user.id), "status": record.status})
    db.commit()
    return record_json(record)


@router.get("/api/v1/classes/{cid}/attendance.xlsx")
def export_attendance(cid: UUID, user: CurrentUser, db: Db):
    teacher(user)
    course = require_class(db, user, cid)
    if close_expired(db, cid, now()): db.commit()
    sessions = db.scalars(select(AttendanceSession).where(AttendanceSession.class_id == cid).order_by(AttendanceSession.started_at)).all()
    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id.in_([item.id for item in sessions]))).all() if sessions else []
    students = {}
    matrix = {}
    for record in records:
        students[record.student_user_id] = (record.student_no, record.student_name)
        matrix[record.student_user_id, record.session_id] = record.status
    current = db.execute(select(User).join(ClassMember, ClassMember.user_id == User.id).where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")).scalars().all()
    for person in current: students.setdefault(person.id, (person.login_name, person.display_name))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "学期考勤"
    sheet.append(["学期", xlsx_cell(course.semester), "教学班", xlsx_cell(course.name)])
    sheet.append(["学号", "姓名", *[xlsx_cell(f"{item.title} ({export_cell(item.started_at)})") for item in sessions], "出勤", "迟到", "请假", "缺勤", "考勤分"])
    for student_id, (student_no, name) in sorted(students.items(), key=lambda item: item[1][0]):
        statuses = [matrix.get((student_id, item.id)) for item in sessions]
        ended = [item for item, session in zip(statuses, sessions) if session.status == "ENDED" and item is not None]
        counts = {key: ended.count(key) for key in STATUS_LABELS}
        score = max(0, 10 - counts["ABSENT"] - counts["LATE"] * 0.5) if ended else None
        labels = [STATUS_LABELS.get(item, "—") for item in statuses]
        sheet.append([xlsx_cell(student_no), xlsx_cell(name), *labels, counts["PRESENT"], counts["LATE"], counts["LEAVE"], counts["ABSENT"], score])
    sheet.freeze_panes = "C3"
    sheet.column_dimensions["A"].width = 19
    sheet.column_dimensions["B"].width = 18
    for column in sheet.columns:
        if column[1].column > 2: sheet.column_dimensions[column[1].column_letter].width = 25
    buffer = io.BytesIO()
    workbook.save(buffer)
    filename = f"{course.semester}-{course.name}-考勤.xlsx"
    return Response(content=buffer.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": content_disposition(filename)})
