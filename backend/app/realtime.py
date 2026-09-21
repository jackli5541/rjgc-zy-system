from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import RealtimeEvent


POLL_INTERVAL_SECONDS = 0.25
MAX_IDLE_POLL_INTERVAL_SECONDS = 2.0
POLL_BATCH_SIZE = 200


def publish_event(
    db: Session,
    *,
    scopes: list[str],
    class_id: UUID | str | None = None,
    resource_type: str | None = None,
    resource_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
    user_ids: list[UUID | str] | None = None,
    roles: list[str] | None = None,
    source_client_id: str | None = None,
    **context,
) -> None:
    payload = {
        "id": uuid4().hex,
        "type": "invalidate",
        "class_id": str(class_id) if class_id else None,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "scopes": sorted(set(scopes)),
        "user_id": str(user_id) if user_id else None,
        "user_ids": [str(value) for value in user_ids or []],
        "roles": roles or [],
        "source_client_id": source_client_id,
        "occurred_at": datetime.now(UTC).isoformat(),
        **context,
    }
    db.add(RealtimeEvent(payload=payload))


@dataclass(frozen=True)
class Subscriber:
    user_id: str
    role: str
    class_id: str
    queue: asyncio.Queue


class RealtimeHub:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._listener_task: asyncio.Task | None = None
        self._stopping = False
        self._last_event_id = 0
        self._has_subscribers = asyncio.Event()

    async def start(self) -> None:
        if self._listener_task and not self._listener_task.done():
            return
        self._stopping = False
        self._last_event_id = await asyncio.to_thread(self._current_event_id)
        self._listener_task = asyncio.create_task(self._listen(), name="sqlserver-realtime-outbox")

    async def stop(self) -> None:
        self._stopping = True
        if self._listener_task:
            self._listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener_task
        self._listener_task = None

    def subscribe(self, user_id: UUID, role: str, class_id: UUID) -> Subscriber:
        subscriber = Subscriber(str(user_id), role, str(class_id), asyncio.Queue(maxsize=32))
        self._subscribers.add(subscriber)
        self._has_subscribers.set()
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)
        if not self._subscribers:
            self._has_subscribers.clear()

    def dispatch(self, payload: dict) -> None:
        for subscriber in tuple(self._subscribers):
            if not self._matches(subscriber, payload):
                continue
            if subscriber.queue.full():
                while not subscriber.queue.empty():
                    with suppress(asyncio.QueueEmpty):
                        subscriber.queue.get_nowait()
                message = {"id": uuid4().hex, "type": "sync_required", "scopes": ["current_view", "notifications"]}
            else:
                message = payload
            with suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(message)

    @staticmethod
    def _matches(subscriber: Subscriber, payload: dict) -> bool:
        target_user = payload.get("user_id")
        if target_user and target_user != subscriber.user_id:
            return False
        target_users = payload.get("user_ids") or []
        if target_users and subscriber.user_id not in target_users:
            return False
        class_id = payload.get("class_id")
        if class_id and class_id != subscriber.class_id:
            return False
        roles = payload.get("roles") or []
        return not roles or subscriber.role in roles

    @staticmethod
    def _current_event_id() -> int:
        with SessionLocal() as db:
            return db.scalar(select(func.max(RealtimeEvent.id))) or 0

    @staticmethod
    def _events_after(event_id: int) -> list[RealtimeEvent]:
        with SessionLocal() as db:
            return list(db.scalars(select(RealtimeEvent).where(RealtimeEvent.id > event_id).order_by(RealtimeEvent.id).limit(POLL_BATCH_SIZE)))

    async def _listen(self) -> None:
        delay = POLL_INTERVAL_SECONDS
        while not self._stopping:
            try:
                if not self._subscribers:
                    self._has_subscribers.clear()
                    if not self._subscribers:
                        await self._has_subscribers.wait()
                    delay = POLL_INTERVAL_SECONDS

                events = await asyncio.to_thread(self._events_after, self._last_event_id)
                for event in events:
                    self.dispatch(event.payload)
                    self._last_event_id = event.id
                if events:
                    delay = POLL_INTERVAL_SECONDS
                else:
                    delay = min(delay * 2, MAX_IDLE_POLL_INTERVAL_SECONDS)
                await asyncio.sleep(0 if len(events) == POLL_BATCH_SIZE else delay)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                self.dispatch({"id": uuid4().hex, "type": "sync_required", "scopes": ["current_view", "notifications"]})


hub = RealtimeHub()
