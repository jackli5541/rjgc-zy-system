from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, update

from app import storage
from app.database import SessionLocal
from app.markdown_assets import DATA_URL_PATTERN, extract_assets
from app.models import FileObject, FileObjectAsset, MarkdownAsset, SubmissionDocument, SubmissionDocumentAsset, SubmissionWorkspace


UTC = timezone.utc


def decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Markdown 文件编码无法识别")


def migrate_document(document_id: UUID) -> tuple[bool, int]:
    uploaded: list[str] = []
    try:
        with SessionLocal.begin() as db:
            document = db.get(SubmissionDocument, document_id)
            if not document or not DATA_URL_PATTERN.search(document.markdown_content):
                return False, 0
            workspace = db.get(SubmissionWorkspace, document.workspace_id)
            rewritten, prepared_assets = extract_assets(document.markdown_content)
            for prepared in prepared_assets:
                key = f"markdown-assets/{workspace.assignment_id}/{workspace.id}/{prepared.id.hex}{prepared.suffix}"
                storage.put_bytes(key, prepared.payload)
                uploaded.append(key)
                db.add(MarkdownAsset(
                    id=prepared.id, assignment_id=workspace.assignment_id, workspace_id=workspace.id,
                    uploader_id=document.updated_by, storage_path=key, original_name=f"migrated-{prepared.id.hex}{prepared.suffix}",
                    mime_type=prepared.mime_type, size_bytes=len(prepared.payload), sha256=prepared.sha256,
                    width=prepared.width, height=prepared.height, orphaned_at=None,
                ))
            db.flush()
            for prepared in prepared_assets:
                db.add(SubmissionDocumentAsset(document_id=document.id, asset_id=prepared.id))
            result = db.execute(
                update(SubmissionDocument)
                .where(SubmissionDocument.id == document.id, SubmissionDocument.revision == document.revision)
                .values(markdown_content=rewritten, revision=document.revision + 1, updated_at=datetime.now(UTC))
            )
            if result.rowcount != 1:
                raise RuntimeError("文档正在被编辑，稍后重试")
        return True, len(uploaded)
    except Exception:
        for key in uploaded:
            storage.delete_object(key)
        raise


def migrate_file(file_id: UUID) -> tuple[bool, int]:
    uploaded: list[str] = []
    old_key = None
    committed = False
    try:
        with SessionLocal.begin() as db:
            file = db.scalar(select(FileObject).where(FileObject.id == file_id).with_for_update())
            if not file or not file.assignment_id or Path(file.original_name).suffix.lower() != ".md":
                return False, 0
            source = decode_text(storage.get_object_bytes(file.storage_path))
            if not DATA_URL_PATTERN.search(source):
                return False, 0
            rewritten, prepared_assets = extract_assets(source)
            for prepared in prepared_assets:
                key = f"markdown-assets/{file.assignment_id}/files/{file.id}/{prepared.id.hex}{prepared.suffix}"
                storage.put_bytes(key, prepared.payload)
                uploaded.append(key)
                db.add(MarkdownAsset(
                    id=prepared.id, assignment_id=file.assignment_id, workspace_id=None,
                    uploader_id=file.owner_id, storage_path=key, original_name=f"migrated-{prepared.id.hex}{prepared.suffix}",
                    mime_type=prepared.mime_type, size_bytes=len(prepared.payload), sha256=prepared.sha256,
                    width=prepared.width, height=prepared.height, orphaned_at=None,
                ))
            db.flush()
            for prepared in prepared_assets:
                db.add(FileObjectAsset(file_id=file.id, asset_id=prepared.id))
            old_key = file.storage_path
            replacement_key = f"{Path(old_key).with_suffix('')}-assets-{uuid4().hex}.md"
            encoded = rewritten.encode("utf-8")
            storage.put_bytes(replacement_key, encoded)
            uploaded.append(replacement_key)
            file.storage_path = replacement_key
            file.size_bytes = len(encoded)
        committed = True
        try:
            storage.delete_object(old_key)
        except Exception as error:
            print(f"old object {old_key}: {error}", flush=True)
        return True, len(uploaded) - 1
    except Exception:
        if not committed:
            for key in uploaded:
                storage.delete_object(key)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Base64 Markdown images into OSS objects.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--documents-only", action="store_true")
    parser.add_argument("--files-only", action="store_true")
    args = parser.parse_args()
    migrated = images = skipped = failed = 0

    if not args.files_only:
        with SessionLocal() as db:
            ids = list(db.scalars(select(SubmissionDocument.id).where(SubmissionDocument.markdown_content.like("%data:image/%")).limit(args.batch_size)).all())
        for item_id in ids:
            try:
                changed, count = migrate_document(item_id)
                migrated += int(changed); images += count; skipped += int(not changed)
            except Exception as error:
                failed += 1
                print(f"document {item_id}: {error}", flush=True)

    if not args.documents_only:
        with SessionLocal() as db:
            ids = list(db.scalars(select(FileObject.id).where(FileObject.assignment_id.is_not(None), FileObject.original_name.like("%.md"))).all())
        for item_id in ids:
            try:
                changed, count = migrate_file(item_id)
                migrated += int(changed); images += count; skipped += int(not changed)
            except Exception as error:
                failed += 1
                print(f"file {item_id}: {error}", flush=True)

    print(f"migrated={migrated} images={images} skipped={skipped} failed={failed}", flush=True)


if __name__ == "__main__":
    main()
