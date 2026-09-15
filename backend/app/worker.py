import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import BackgroundJob, FileObject, ImportBatch, LoginSession
from app.settings import settings


def fail_preview(job_id: UUID, file_id: UUID | None, reason: str) -> None:
    with SessionLocal.begin() as db:
        job = db.get(BackgroundJob, job_id)
        if job:
            job.status = "FAILED"
            job.last_error = reason[:500]
        if file_id:
            file = db.get(FileObject, file_id)
            if file:
                file.preview_status = "FAILED"
                file.preview_error = reason[:500]


def process_preview(job_id: UUID, file_id: UUID) -> None:
    with SessionLocal() as db:
        file = db.get(FileObject, file_id)
        if not file:
            fail_preview(job_id, None, "找不到待预览文件")
            return
        source = settings.file_root / file.storage_path
        if not source.is_file():
            fail_preview(job_id, file_id, "原文件存储不可用")
            return
        preview_relative = f"previews/{file.id.hex}.pdf"
        preview_target = settings.file_root / preview_relative
        original_name = file.original_name

    temp_root = settings.file_root / ".preview-tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            result = subprocess.run(
                [settings.office_converter, "--headless", "--convert-to", "pdf", "--outdir", directory, str(source)],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            converted = Path(directory) / f"{Path(original_name).stem}.pdf"
            if result.returncode or not converted.is_file():
                detail = (result.stderr or result.stdout or "转换工具未生成 PDF").strip()
                raise RuntimeError(detail[:500])
            preview_target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(converted, preview_target)
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        fail_preview(job_id, file_id, f"Office 预览转换失败：{error}")
        return

    with SessionLocal.begin() as db:
        job = db.get(BackgroundJob, job_id)
        file = db.get(FileObject, file_id)
        if job:
            job.status = "COMPLETED"
            job.result_path = preview_relative
            job.last_error = None
        if file:
            file.preview_status = "READY"
            file.preview_storage_path = preview_relative
            file.preview_error = None


def run_once() -> None:
    with SessionLocal.begin() as db:
        current = datetime.now(UTC)
        db.execute(delete(LoginSession).where(LoginSession.expires_at < current))
        db.execute(delete(ImportBatch).where(ImportBatch.status == "PREVIEWED", ImportBatch.created_at < current - timedelta(days=1)))
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.status == "PENDING", BackgroundJob.available_at <= current).with_for_update(skip_locked=True).limit(1))
        if not job:
            return
        job.status = "RUNNING"
        job.locked_at = current
        job.attempts += 1
        job_id = job.id
        job_kind = job.kind
        try:
            file_id = UUID(job.payload["file_id"]) if job_kind == "FILE_PREVIEW" and job.payload.get("file_id") else None
        except (KeyError, TypeError, ValueError):
            file_id = None

    if job_kind == "FILE_PREVIEW" and file_id:
        process_preview(job_id, file_id)
    else:
        fail_preview(job_id, file_id, "当前任务类型没有可用处理器")


def main() -> None:
    while True:
        try:
            run_once()
        except Exception as error:
            print(f"worker cycle failed: {type(error).__name__}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
