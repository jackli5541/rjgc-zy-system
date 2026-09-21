import asyncio

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import RealtimeEvent
from app.realtime import RealtimeHub, publish_event


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

        hub.dispatch({"id": "three", "type": "invalidate", "user_ids": [student.user_id], "scopes": ["workspace"]})
        assert (await student.queue.get())["id"] == "three"
        assert teacher.queue.empty()

    asyncio.run(scenario())


def test_realtime_event_is_visible_after_commit():
    with SessionLocal.begin() as db:
        publish_event(db, class_id="00000000-0000-0000-0000-000000000010", scopes=["submissions"], resource_type="assignment", resource_id="00000000-0000-0000-0000-000000000011")

    with SessionLocal() as db:
        event = db.scalar(select(RealtimeEvent).order_by(RealtimeEvent.id.desc()).limit(1))

    assert event.payload["scopes"] == ["submissions"]
    assert event.payload["resource_type"] == "assignment"


def test_realtime_event_rolls_back_with_transaction():
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(RealtimeEvent))
        publish_event(db, scopes=["audit"], resource_type="test")
        db.rollback()

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RealtimeEvent)) == before


def test_realtime_hub_polls_committed_events():
    async def scenario():
        hub = RealtimeHub()
        await hub.start()
        subscriber = hub.subscribe("00000000-0000-0000-0000-000000000001", "TEACHER", "00000000-0000-0000-0000-000000000010")
        try:
            with SessionLocal.begin() as db:
                publish_event(db, class_id=subscriber.class_id, scopes=["dashboard"])
            message = await asyncio.wait_for(subscriber.queue.get(), timeout=2)
            assert message["scopes"] == ["dashboard"]
        finally:
            await hub.stop()

    asyncio.run(scenario())


def test_realtime_hub_sleeps_until_first_subscriber(monkeypatch):
    async def scenario():
        hub = RealtimeHub()
        poll_count = 0

        monkeypatch.setattr(hub, "_current_event_id", lambda: 0)

        def events_after(_):
            nonlocal poll_count
            poll_count += 1
            return []

        monkeypatch.setattr(hub, "_events_after", events_after)
        await hub.start()
        try:
            await asyncio.sleep(0.35)
            assert poll_count == 0

            subscriber = hub.subscribe(
                "00000000-0000-0000-0000-000000000001",
                "TEACHER",
                "00000000-0000-0000-0000-000000000010",
            )
            await asyncio.sleep(0.6)
            assert poll_count > 0

            hub.unsubscribe(subscriber)
            stopped_at = poll_count
            await asyncio.sleep(2.2)
            assert poll_count <= stopped_at + 1
        finally:
            await hub.stop()

    asyncio.run(scenario())
