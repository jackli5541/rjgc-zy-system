from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Callable
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from app.settings import settings


DATA_URL_PATTERN = re.compile(r"data:image/(?P<subtype>png|jpeg|gif|webp|svg\+xml);base64,(?P<payload>[A-Za-z0-9+/=]+)", re.IGNORECASE)
IMAGE_FORMATS = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "GIF": (".gif", "image/gif"),
    "WEBP": (".webp", "image/webp"),
}
SVG_FORBIDDEN_PATTERN = re.compile(rb"<\s*script|on[a-z]+\s*=|<\s*foreignobject|<!entity", re.IGNORECASE)
SVG_DIMENSION_PATTERN = re.compile(rb'<svg\b[^>]*?\bwidth="\s*([\d.]+)[a-z%]*"[^>]*?\bheight="\s*([\d.]+)[a-z%]*"', re.IGNORECASE | re.DOTALL)
SVG_VIEWBOX_PATTERN = re.compile(rb'<svg\b[^>]*?\bviewBox="\s*[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)\s*"', re.IGNORECASE | re.DOTALL)
DEFAULT_ASSET_URL = lambda asset_id: f"/api/v1/markdown-assets/{asset_id}/content"  # noqa: E731


@dataclass
class PreparedAsset:
    id: UUID
    payload: bytes
    suffix: str
    mime_type: str
    sha256: str
    width: int
    height: int


def _svg_dimensions(payload: bytes) -> tuple[int, int]:
    match = SVG_DIMENSION_PATTERN.search(payload) or SVG_VIEWBOX_PATTERN.search(payload)
    if not match:
        return 0, 0
    try:
        return int(float(match.group(1))), int(float(match.group(2)))
    except ValueError:
        return 0, 0


def _prepare_svg_payload(payload: bytes) -> tuple[int, int]:
    if b"<svg" not in payload.lower():
        raise ValueError("图片内容不是合法的 SVG")
    if SVG_FORBIDDEN_PATTERN.search(payload):
        raise ValueError("SVG 图片包含不受支持的脚本或事件属性")
    return _svg_dimensions(payload)


def prepare_asset(encoded: str, subtype: str = "png") -> PreparedAsset:
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("Base64 图片编码损坏") from error
    if not payload or len(payload) > settings.markdown_image_max_bytes:
        raise ValueError("图片为空或超过大小限制")
    if subtype.lower() == "svg+xml":
        width, height = _prepare_svg_payload(payload)
        suffix, mime_type = ".svg", "image/svg+xml"
    else:
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


def extract_assets(markdown: str, url_for: Callable[[UUID], str] = DEFAULT_ASSET_URL) -> tuple[str, list[PreparedAsset]]:
    by_hash: dict[str, PreparedAsset] = {}

    def replace(match: re.Match) -> str:
        prepared = prepare_asset(match.group("payload"), match.group("subtype"))
        asset = by_hash.setdefault(prepared.sha256, prepared)
        return url_for(asset.id)

    return DATA_URL_PATTERN.sub(replace, markdown), list(by_hash.values())
