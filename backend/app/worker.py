import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import BackgroundJob, ImportBatch, LoginSession


def run_once() -> None:
    with SessionLocal.begin() as db:
        current = datetime.now(UTC)
        db.execute(delete(LoginSession).where(LoginSession.expires_at < current))
        db.execute(delete(ImportBatch).where(ImportBatch.status == "PREVIEWED", ImportBatch.created_at < current - timedelta(days=1)))
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.status == "PENDING", BackgroundJob.available_at <= current).with_for_update(skip_locked=True).limit(1))
        if job:
            job.status = "FAILED"
            job.attempts += 1
            job.last_error = "当前任务类型没有可用处理器"


def main() -> None:
    while True:
        try:
            run_once()
        except Exception as error:
            print(f"worker cycle failed: {type(error).__name__}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
