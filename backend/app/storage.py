from __future__ import annotations

from pathlib import Path
from typing import Iterator

import oss2
from oss2.exceptions import NoSuchKey

from app.settings import settings

_bucket: oss2.Bucket | None = None


def _bucket_client() -> oss2.Bucket:
    global _bucket
    if _bucket is None:
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        _bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)
    return _bucket


def _object_key(key: str) -> str:
    return f"{settings.oss_key_prefix}{key}"


def put_object(key: str, local_path: Path) -> None:
    _bucket_client().put_object_from_file(_object_key(key), str(local_path))


def put_bytes(key: str, data: bytes) -> None:
    _bucket_client().put_object(_object_key(key), data)


def get_object_stream(key: str) -> Iterator[bytes]:
    return _bucket_client().get_object(_object_key(key))


def get_object_bytes(key: str) -> bytes:
    return _bucket_client().get_object(_object_key(key)).read()


def sign_get_url(key: str, expires: int, params: dict[str, str] | None = None) -> str:
    return _bucket_client().sign_url("GET", _object_key(key), expires, params=params)


def delete_object(key: str) -> None:
    try:
        _bucket_client().delete_object(_object_key(key))
    except NoSuchKey:
        pass


def object_exists(key: str) -> bool:
    return _bucket_client().object_exists(_object_key(key))


def bucket_reachable() -> bool:
    _bucket_client().get_bucket_info()
    return True
