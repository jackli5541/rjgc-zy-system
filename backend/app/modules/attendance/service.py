from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.utils import now
from app.core.audit import audit
from app.models import AttendanceRecord, AttendanceSession

CODE_PERIOD_SECONDS = 30
CODE_GRACE_SECONDS = 5
STATUS_LABELS = {"PENDING": "未签到", "PRESENT": "出勤", "LATE": "迟到", "ABSENT": "缺勤", "LEAVE": "请假"}


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def current_code(session: AttendanceSession, at: datetime) -> str:
    step = int(at.timestamp()) // CODE_PERIOD_SECONDS
    digest = hmac.new(session.code_secret, step.to_bytes(8, "big"), hashlib.sha256).digest()
    offset = digest[-1] & 15
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7fffffff
    return f"{value % 1000000:06d}"


def code_valid(session: AttendanceSession, code: str, at: datetime) -> bool:
    if hmac.compare_digest(current_code(session, at), code):
        return True
    return int(at.timestamp()) % CODE_PERIOD_SECONDS < CODE_GRACE_SECONDS and hmac.compare_digest(
        current_code(session, at - timedelta(seconds=CODE_PERIOD_SECONDS)), code
    )


def effective_status(session: AttendanceSession, at: datetime) -> str:
    return "ENDED" if session.status == "ACTIVE" and aware(session.expires_at) <= at else session.status


def finish_session(db: Session, session: AttendanceSession, at: datetime, user=None, automatic: bool = False) -> None:
    session.status = "ENDED"
    session.ended_at = min(at, aware(session.expires_at))
    db.execute(update(AttendanceRecord).where(AttendanceRecord.session_id == session.id, AttendanceRecord.status == "PENDING").values(status="ABSENT"))
    audit(db, user, "ATTENDANCE_ENDED", "attendance_session", str(session.id), {"class_id": str(session.class_id), "automatic": automatic})


def close_expired(db: Session, class_id: UUID, at: datetime) -> bool:
    due = (AttendanceSession.class_id == class_id, AttendanceSession.status == "ACTIVE", AttendanceSession.expires_at <= at)
    if db.scalar(select(AttendanceSession.id).where(*due).limit(1)) is None:
        return False
    sessions = db.scalars(select(AttendanceSession).where(*due).with_for_update()).all()
    changed = False
    for session in sessions:
        finish_session(db, session, at, automatic=True)
        changed = True
    if changed:
        db.flush()
    return changed


def process_due_attendance(db: Session, at: datetime) -> int:
    class_ids = db.scalars(select(AttendanceSession.class_id).where(AttendanceSession.status == "ACTIVE", AttendanceSession.expires_at <= at).limit(20)).all()
    return sum(close_expired(db, class_id, at) for class_id in set(class_ids))


def session_json(session: AttendanceSession, records: list[AttendanceRecord] | None = None, at: datetime | None = None, include_code: bool = False) -> dict:
    at = at or now()
    data = {
        "id": str(session.id), "class_id": str(session.class_id), "title": session.title,
        "status": effective_status(session, at), "started_at": aware(session.started_at).isoformat(),
        "expires_at": aware(session.expires_at).isoformat(),
        "ended_at": aware(session.ended_at).isoformat() if session.ended_at else None,
    }
    if records is not None:
        data["total"] = len(records)
        data["present"] = sum(item.status == "PRESENT" for item in records)
        data["late"] = sum(item.status == "LATE" for item in records)
        data["absent"] = sum(item.status == "ABSENT" for item in records)
        data["pending"] = sum(item.status == "PENDING" for item in records)
        data["leave"] = sum(item.status == "LEAVE" for item in records)
    if include_code and data["status"] == "ACTIVE":
        data["code"] = current_code(session, at)
        data["code_expires_at"] = datetime.fromtimestamp((int(at.timestamp()) // CODE_PERIOD_SECONDS + 1) * CODE_PERIOD_SECONDS, timezone.utc).isoformat()
    return data


def record_json(record: AttendanceRecord) -> dict:
    return {
        "id": str(record.id), "student_id": str(record.student_user_id),
        "student_no": record.student_no, "student_name": record.student_name,
        "status": record.status, "checked_in_at": aware(record.checked_in_at).isoformat() if record.checked_in_at else None,
        "source": record.source, "note": record.note,
    }


def roster_records(db: Session, session: AttendanceSession) -> list[AttendanceRecord]:
    return db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id).order_by(AttendanceRecord.student_no)).all()
