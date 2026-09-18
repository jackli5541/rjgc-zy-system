"""One-time migration: upload existing local files to the OSS bucket.

`FileObject.storage_path` is used unchanged as the OSS object key, so the
database needs no changes. Only uploads — never deletes local files or
touches the database. Safe to re-run: objects already present in OSS are
skipped.

Run from the repository root:
    .\\backend\\.venv\\Scripts\\python.exe .\\scripts\\migrate-files-to-oss.py [--source-dir PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app import storage  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import FileObject  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default="./data/files", help="旧的本地文件根目录（相对 backend/ 或绝对路径）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不实际上传")
    args = parser.parse_args()
    source_dir = Path(args.source_dir).resolve()

    uploaded, skipped, missing, failed = 0, 0, 0, []
    with SessionLocal() as db:
        files = db.scalars(select(FileObject)).all()
        total = len(files)
        for index, file in enumerate(files, 1):
            local_path = source_dir / file.storage_path
            if not local_path.is_file():
                missing += 1
                print(f"[{index}/{total}] 缺失 {file.storage_path}")
                continue
            if storage.object_exists(file.storage_path):
                skipped += 1
                continue
            if args.dry_run:
                uploaded += 1
                print(f"[{index}/{total}] 将上传 {file.storage_path}")
                continue
            try:
                storage.put_object(file.storage_path, local_path)
                uploaded += 1
                print(f"[{index}/{total}] 已上传 {file.storage_path}")
            except Exception as error:
                failed.append((file.storage_path, str(error)))
                print(f"[{index}/{total}] 上传失败 {file.storage_path}: {error}")

    print()
    print(f"成功 {uploaded} / 跳过（OSS 已存在）{skipped} / 本地缺失 {missing} / 上传失败 {len(failed)}")
    if failed:
        print("失败清单：")
        for key, error in failed:
            print(f"  {key}: {error}")


if __name__ == "__main__":
    main()
