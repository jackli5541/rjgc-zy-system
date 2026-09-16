import asyncio
import json

import psycopg
from sqlalchemy import text

from app.database import SessionLocal
from app.realtime import CHANNEL, RealtimeHub, publish_event
from app.settings import settings


def test_realtime_hub_filters_class_role_and_user():
    async def scenario():
        hub = RealtimeHub()
        teacher = hub.subscribe("00000000-0000-0000-0000-000000000001", "TEACHER", "00000000-0000-0000-0000-000000000010")
        student = hub.subscribe("00000000-0000-0000-0000-000000000002", "STUDENT", "00000000-0000-0000-0000-000000000010")
        other_class = hub.subscribe("00000000-0000-0000-0000-000000000003", "TEACHER", "00000000-0000-0000-0000-000000000020")

        hub.dispatch({"id": "one", "type": "invalidate", "class_id": teacher.class_id, "roles": ["TEACHER"], "scopes": ["submissions"]})
        assert (await teacher.queue.get())["id"] == "one"
        assert student.queue.empty()
        assert other_class.queue.empty()

        hub.dispatch({"id": "two", "type": "invalidate", "user_id": student.user_id, "scopes": ["notifications"]})
        assert (await student.queue.get())["id"] == "two"
        assert teacher.queue.empty()

    asyncio.run(scenario())


def test_realtime_event_is_delivered_after_commit():
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as listener:
        listener.execute(f"LISTEN {CHANNEL}")
        with SessionLocal.begin() as db:
            publish_event(db, class_id="00000000-0000-0000-0000-000000000010", scopes=["submissions"], resource_type="assignment", resource_id="00000000-0000-0000-0000-000000000011")
        messages = list(listener.notifies(timeout=2, stop_after=1))

    assert len(messages) == 1
    payload = json.loads(messages[0].payload)
    assert payload["scopes"] == ["submissions"]
    assert payload["resource_type"] == "assignment"


def test_realtime_event_rolls_back_with_transaction():
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as listener:
        listener.execute(f"LISTEN {CHANNEL}")
        with SessionLocal() as db:
            publish_event(db, scopes=["audit"], resource_type="test")
            db.rollback()
        assert list(listener.notifies(timeout=0.2, stop_after=1)) == []
