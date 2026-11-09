"""把学生提交和评分标准文件抽成纯文本，供 MCP 工具分页返回。失败不抛异常，返回原因。"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from app import storage
from app.core.html import html_to_text
from app.core.utils import decode_text_file
from app.settings import settings

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".html", ".htm"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx"}
MAX_EXTRACT_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200


def is_readable_suffix(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_SUFFIXES


def _pdf_text(payload: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload))
    pages = []
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            pages.append(f"[已截断：PDF 超过 {MAX_PDF_PAGES} 页]")
            break
        pages.append(f"--- 第 {index + 1} 页 ---\n{(page.extract_text() or '').strip()}")
    return "\n\n".join(pages)


def _docx_text(payload: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(payload))
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(lines)


@lru_cache(maxsize=16)
def _cached(storage_path: str, name: str, size_bytes: int) -> tuple[str | None, str | None]:
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return None, f"暂不支持从 {suffix or '无扩展名'} 文件抽取文本，请教师人工查看"
    if size_bytes > MAX_EXTRACT_BYTES:
        return None, "文件超过 20MB，无法抽取文本"
    if settings.storage_local_only and settings.storage_backend != "local":
        return None, "本地验证模式只能读取本地文件"
    try:
        payload = storage.get_object_bytes(storage_path)
        if suffix == ".pdf":
            text = _pdf_text(payload)
        elif suffix == ".docx":
            text = _docx_text(payload)
        else:
            text = decode_text_file(payload)
            if suffix in {".html", ".htm"}:
                text = html_to_text(text)
    except Exception:
        return None, "文件无法解析（可能已损坏、加密或为扫描件），请教师人工查看"
    if not text.strip():
        return None, "文件没有可抽取的文字（可能是扫描件或图片），请教师人工查看"
    return text.strip(), None


def extract_text(file) -> tuple[str | None, str | None]:
    """返回 (文本, 问题说明)。两者恰有一个为 None。"""
    return _cached(file.storage_path, file.original_name, file.size_bytes)
