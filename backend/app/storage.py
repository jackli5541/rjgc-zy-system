from __future__ import annotations

from pathlib import Path
import hashlib
import hmac
import json
import shutil
import time
from urllib.parse import urlencode
from typing import Iterator

import oss2
from oss2.exceptions import NoSuchKey

from app.settings import settings

_bucket: oss2.Bucket | None = None


def local_path(key: str) -> Path:
    root = settings.local_storage_root.resolve()
    target = (root / key).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("Invalid storage key")
    return target


def local_signature(key: str, expires: int, params: str) -> str:
    if not settings.local_storage_secret:
        raise ValueError("LOCAL_STORAGE_SECRET is required for local storage")
    payload = json.dumps([key, expires, params], ensure_ascii=True).encode()
    return hmac.new(settings.local_storage_secret.encode(), payload, hashlib.sha256).hexdigest()


def _bucket_client() -> oss2.Bucket:
    global _bucket
    if settings.storage_local_only:
        raise RuntimeError("本地验证模式禁止访问 OSS，请设置 STORAGE_BACKEND=local")
    if _bucket is None:
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        _bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)
    return _bucket


def _object_key(key: str) -> str:
    return f"{settings.oss_key_prefix}{key}"


def put_object(key: str, source_path: Path) -> None:
    if settings.storage_backend == "local":
        target = local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        return
    _bucket_client().put_object_from_file(_object_key(key), str(source_path))


def put_bytes(key: str, data: bytes) -> None:
    if settings.storage_backend == "local":
        target = local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return
    _bucket_client().put_object(_object_key(key), data)


def get_object_stream(key: str) -> Iterator[bytes]:
    if settings.storage_backend == "local":
        def chunks():
            with local_path(key).open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    yield chunk
        return chunks()
    return _bucket_client().get_object(_object_key(key))


def get_object_bytes(key: str) -> bytes:
    if settings.storage_backend == "local":
        return local_path(key).read_bytes()
    return _bucket_client().get_object(_object_key(key)).read()


def sign_get_url(key: str, expires: int, params: dict[str, str] | None = None) -> str:
    if settings.storage_backend == "local":
        deadline = int(time.time()) + expires
        options = json.dumps(params or {}, sort_keys=True)
        return "/api/v1/local-files?" + urlencode({"key": key, "expires": deadline, "params": options, "signature": local_signature(key, deadline, options)})
    return _bucket_client().sign_url("GET", _object_key(key), expires, params=params)


def delete_object(key: str) -> None:
    if settings.storage_backend == "local":
        local_path(key).unlink(missing_ok=True)
        return
    try:
        _bucket_client().delete_object(_object_key(key))
    except NoSuchKey:
        pass


def object_exists(key: str) -> bool:
    if settings.storage_backend == "local":
        return local_path(key).is_file()
    return _bucket_client().object_exists(_object_key(key))


def bucket_reachable() -> bool:
    if settings.storage_backend == "local":
        settings.local_storage_root.mkdir(parents=True, exist_ok=True)
        return True
    _bucket_client().get_bucket_info()
    return True
