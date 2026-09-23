from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote


UTC = timezone.utc


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    quoted = quote(filename)
    if quoted != filename:
        return f"{disposition}; filename*=utf-8''{quoted}"
    return f'{disposition}; filename="{filename}"'


def decode_text_file(payload: bytes) -> str:
    encodings = ["utf-8-sig"]
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("gb18030")
    for encoding in encodings:
        try: return payload.decode(encoding)
        except UnicodeDecodeError: continue
    raise UnicodeDecodeError("unknown", payload, 0, len(payload), "unsupported text encoding")


def now() -> datetime: return datetime.now(UTC)
