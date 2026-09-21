from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from app.settings import settings


DATA_URL_PATTERN = re.compile(r"data:image/(?P<subtype>png|jpeg|gif|webp);base64,(?P<payload>[A-Za-z0-9+/=]+)", re.IGNORECASE)
IMAGE_FORMATS = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "GIF": (".gif", "image/gif"),
    "WEBP": (".webp", "image/webp"),
}


@dataclass
class PreparedAsset:
    id: UUID
    payload: bytes
    suffix: str
    mime_type: str
    sha256: str
    width: int
    height: int


def prepare_asset(encoded: str) -> PreparedAsset:
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("Base64 图片编码损坏") from error
    if not payload or len(payload) > settings.markdown_image_max_bytes:
        raise ValueError("图片为空或超过大小限制")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image_format = image.format
            width, height = image.size
            if image_format not in IMAGE_FORMATS:
                raise ValueError("图片格式不受支持")
            if width <= 0 or height <= 0 or width * height > settings.markdown_image_max_pixels:
                raise ValueError("图片像素尺寸过大")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("图片内容损坏") from error
    suffix, mime_type = IMAGE_FORMATS[image_format]
    return PreparedAsset(uuid4(), payload, suffix, mime_type, hashlib.sha256(payload).hexdigest(), width, height)


def extract_assets(markdown: str) -> tuple[str, list[PreparedAsset]]:
    by_hash: dict[str, PreparedAsset] = {}

    def replace(match: re.Match) -> str:
        prepared = prepare_asset(match.group("payload"))
        asset = by_hash.setdefault(prepared.sha256, prepared)
        return f"/api/v1/markdown-assets/{asset.id}/content"

    return DATA_URL_PATTERN.sub(replace, markdown), list(by_hash.values())
