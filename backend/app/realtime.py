from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.settings import settings


CHANNEL = "coursework_events"


def _database_dsn() -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def publish_event(
    db: Session,
    *,
    scopes: list[str],
    class_id: UUID | str | None = None,
    resource_type: str | None = None,
    resource_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
    roles: list[str] | None = None,
    source_client_id: str | None = None,
) -> None:
    payload = {
        "id": uuid4().hex,
        "type": "invalidate",
        "class_id": str(class_id) if class_id else None,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "scopes": sorted(set(scopes)),
        "user_id": str(user_id) if user_id else None,
        "roles": roles or [],
        "source_client_id": source_client_id,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    db.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": json.dumps(payload, separators=(",", ":"))})


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

    async def start(self) -> None:
        if self._listener_task and not self._listener_task.done():
            return
        self._stopping = False
        self._listener_task = asyncio.create_task(self._listen(), name="postgres-realtime-listener")

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
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

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
        class_id = payload.get("class_id")
        if class_id and class_id != subscriber.class_id:
            return False
        roles = payload.get("roles") or []
        return not roles or subscriber.role in roles

    async def _listen(self) -> None:
        delay = 1
        while not self._stopping:
            try:
                connection = await psycopg.AsyncConnection.connect(_database_dsn(), autocommit=True)
                async with connection:
                    await connection.execute(f"LISTEN {CHANNEL}")
                    if delay > 1:
                        self.dispatch({"id": uuid4().hex, "type": "sync_required", "scopes": ["current_view", "notifications"]})
                    delay = 1
                    async for notification in connection.notifies():
                        try:
                            self.dispatch(json.loads(notification.payload))
                        except (TypeError, ValueError):
                            continue
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


hub = RealtimeHub()
