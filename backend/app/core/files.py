from __future__ import annotations

import re
from sqlalchemy.orm import Session

from app.models import BackgroundJob, User
from app.core.utils import now

BASE64_IMAGE_PATTERN = re.compile(r"data:image/[^;,\s]+;base64,", re.IGNORECASE)


MARKDOWN_IMAGE_FORMATS = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "GIF": (".gif", "image/gif"),
    "WEBP": (".webp", "image/webp"),
}


def enqueue_archive_export(db: Session, user: User, kind: str, payload: dict, filename: str) -> dict:
    job = BackgroundJob(
        kind="ARCHIVE_EXPORT",
        payload={**payload, "archive_kind": kind, "requester_id": str(user.id), "filename": filename},
        status="ARCHIVE_PENDING",
        available_at=now(),
    )
    db.add(job)
    db.commit()
    return {"id": str(job.id), "status": "PENDING", "filename": filename}
