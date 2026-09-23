from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from uuid import UUID

from app.models import AttendanceScoreManual, ClassMember
from app.core.audit import audit
from app.core.deps import CsrfUser, Db, require_writable_class, teacher
from app.core.errors import ApiError
from app.modules.attendance.schemas import AttendanceScoreIn

router = APIRouter()

@router.put("/api/v1/classes/{cid}/students/{student_id}/attendance-score")
def set_attendance_score(cid: UUID, student_id: UUID, data: AttendanceScoreIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    if not db.scalar(select(ClassMember.id).where(ClassMember.class_id == cid, ClassMember.user_id == student_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")):
        raise ApiError(404, "STUDENT_NOT_FOUND", "该学生不在本班")
    record = db.scalar(select(AttendanceScoreManual).where(AttendanceScoreManual.class_id == cid, AttendanceScoreManual.student_user_id == student_id))
    if data.score is None:
        if record: db.delete(record)
        db.commit()
        return {"class_id": str(cid), "student_id": str(student_id), "score": None}
    if not record:
        record = AttendanceScoreManual(class_id=cid, student_user_id=student_id)
        db.add(record)
    record.score = data.score
    record.graded_by = user.id
    audit(db, user, "ATTENDANCE_SCORE_SET", "attendance_score_manual", str(student_id), {"class_id": str(cid), "score": float(data.score)})
    db.commit(); db.refresh(record)
    return {"class_id": str(cid), "student_id": str(student_id), "score": float(record.score)}
