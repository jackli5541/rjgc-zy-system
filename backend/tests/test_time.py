from datetime import datetime, timedelta, timezone

from app.core.utils import now
from app.database import SessionLocal
from app.models import Notification, User
from app.modules.grades.service import export_cell
from sqlalchemy import select


def test_export_time_uses_beijing_timezone():
    assert export_cell(datetime(2026, 9, 29, 20)) == "2026-09-30 04:00:00"
    assert export_cell(datetime(2026, 9, 29, 20, tzinfo=timezone.utc)) == "2026-09-30 04:00:00"
    assert export_cell(datetime(2026, 9, 30, 4, tzinfo=timezone(timedelta(hours=8)))) == "2026-09-30 04:00:00"


def test_notification_timestamp_is_utc_and_preserves_explicit_time():
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login_name == "teacher"))
        before = now()
        explicit_time = datetime(2026, 9, 30, 4, tzinfo=timezone(timedelta(hours=8)))
        generated = Notification(user_id=user.id, kind="TEST", title="UTC timestamp")
        explicit = Notification(user_id=user.id, kind="TEST", title="Explicit timestamp", created_at=explicit_time)
        db.add_all([generated, explicit])
        db.flush()
        db.refresh(generated)
        db.refresh(explicit)
        assert generated.created_at.utcoffset() == timedelta(0)
        assert before <= generated.created_at <= now()
        assert explicit.created_at == explicit_time
