from __future__ import annotations

import csv
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import storage
from app.models import Assignment, ClassMember, FileObject, FileObjectAsset, MarkdownAsset, Submission, SubmissionDocument, SubmissionDocumentAsset, SubmissionVersion, Team, User, VersionFile


ASSET_URL_PATTERN = re.compile(r"/api/v1/markdown-assets/([0-9a-fA-F-]{36})/content(?:\?[^\s)\"']*)?")


def _decode_markdown(data: bytes) -> str:
    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("gb18030")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", data, 0, len(data), "Markdown 文件编码无法识别")


def _temporary_zip() -> Path:
    handle, name = tempfile.mkstemp(prefix="coursework-export-", suffix=".zip")
    os.close(handle)
    return Path(name)


def _markdown_with_assets(db: Session, bundle: zipfile.ZipFile, folder: str, file: FileObject, written: set[tuple[str, UUID]]) -> bytes:
    source = _decode_markdown(storage.get_object_bytes(file.storage_path))
    asset_ids = set(db.scalars(select(FileObjectAsset.asset_id).where(FileObjectAsset.file_id == file.id)).all())
    assets = {item.id: item for item in db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(asset_ids))).all()} if asset_ids else {}

    def replace(match: re.Match) -> str:
        asset = assets.get(UUID(match.group(1)))
        if not asset:
            return match.group(0)
        suffix = Path(asset.storage_path).suffix.lower()
        archive_name = f"{folder + '/' if folder else ''}images/{asset.id}{suffix}"
        marker = (folder, asset.id)
        if marker not in written:
            bundle.writestr(archive_name, storage.get_object_bytes(asset.storage_path))
            written.add(marker)
        return f"images/{asset.id}{suffix}"

    return ASSET_URL_PATTERN.sub(replace, source).encode("utf-8")


def _write_file(db: Session, bundle: zipfile.ZipFile, archive_name: str, folder: str, file: FileObject, written: set[tuple[str, UUID]]) -> None:
    if Path(file.original_name).suffix.lower() == ".md":
        bundle.writestr(archive_name, _markdown_with_assets(db, bundle, folder, file, written))
        return
    with bundle.open(archive_name, "w") as destination:
        for chunk in storage.get_object_stream(file.storage_path):
            destination.write(chunk)


def build_materials_archive(db: Session, file_ids: list[UUID]) -> Path:
    files = db.scalars(select(FileObject).where(FileObject.id.in_(file_ids)).order_by(FileObject.created_at)).all()
    target = _temporary_zip()
    try:
        used_names = set()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for file in files:
                original = Path(file.original_name).name
                name, index = original, 1
                while name.casefold() in used_names:
                    name = f"{Path(original).stem} ({index}){Path(original).suffix}"
                    index += 1
                used_names.add(name.casefold())
                _write_file(db, bundle, name, "", file, set())
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def build_workspace_document_archive(db: Session, document_id: UUID) -> Path:
    document = db.get(SubmissionDocument, document_id)
    if not document:
        raise ValueError("在线文档不存在")
    asset_ids = set(db.scalars(
        select(SubmissionDocumentAsset.asset_id).where(SubmissionDocumentAsset.document_id == document.id)
    ).all())
    assets = {
        item.id: item for item in db.scalars(select(MarkdownAsset).where(MarkdownAsset.id.in_(asset_ids))).all()
    } if asset_ids else {}
    target = _temporary_zip()
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            def replace(match: re.Match) -> str:
                asset = assets.get(UUID(match.group(1)))
                if not asset:
                    return match.group(0)
                suffix = Path(asset.storage_path).suffix.lower()
                bundle.writestr(f"images/{asset.id}{suffix}", storage.get_object_bytes(asset.storage_path))
                return f"images/{asset.id}{suffix}"

            markdown = ASSET_URL_PATTERN.sub(replace, document.markdown_content)
            bundle.writestr(Path(document.name).name, markdown.encode("utf-8"))
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def build_portfolio_archive(db: Session, class_id: UUID, student_id: UUID | None = None) -> Path:
    from app.student_portfolio import portfolio, safe_name, write_student_archive

    student_ids = [student_id] if student_id else db.scalars(
        select(ClassMember.user_id)
        .where(ClassMember.class_id == class_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")
        .order_by(ClassMember.user_id)
    ).all()
    target = _temporary_zip()
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for current_id in student_ids:
                data = portfolio(db, class_id, current_id)
                member = data["member"]
                root = f"{safe_name(member['student_no'])}_{safe_name(member['name'])}/" if student_id is None else ""
                write_student_archive(bundle, db, data, root)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def build_assignment_archive(db: Session, assignment_id: UUID) -> Path:
    rows = db.execute(
        select(Submission, SubmissionVersion)
        .join(SubmissionVersion, and_(SubmissionVersion.submission_id == Submission.id, SubmissionVersion.version_no == Submission.current_version_no))
        .where(Submission.assignment_id == assignment_id, Submission.status == "SUBMITTED")
    ).all()
    version_ids = [version.id for _, version in rows]
    files_by_version: dict[UUID, list[FileObject]] = {}
    if version_ids:
        for version_id, file in db.execute(select(VersionFile.version_id, FileObject).join(FileObject, FileObject.id == VersionFile.file_id).where(VersionFile.version_id.in_(version_ids))):
            files_by_version.setdefault(version_id, []).append(file)
    user_ids = {submission.owner_user_id for submission, _ in rows if submission.owner_user_id}
    team_ids = {submission.owner_team_id for submission, _ in rows if submission.owner_team_id}
    users = {item.id: item for item in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    teams = {item.id: item for item in db.scalars(select(Team).where(Team.id.in_(team_ids))).all()} if team_ids else {}
    target = _temporary_zip()
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            written: set[tuple[str, UUID]] = set()
            for submission, version in rows:
                owner = users.get(submission.owner_user_id) if submission.owner_user_id else teams.get(submission.owner_team_id)
                folder = owner.login_name if isinstance(owner, User) else owner.name
                for file in files_by_version.get(version.id, []):
                    _write_file(db, bundle, f"{folder}/{file.original_name}", folder, file, written)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def build_team_archive(db: Session, team_id: UUID) -> Path:
    from app.modules.assignments.service import displayed_submission_grade_result, missing_submission_grade_result
    from app.modules.grades.service import export_cell

    team = db.get(Team, team_id)
    assignments = db.scalars(select(Assignment).where(
        Assignment.class_id == team.class_id,
        Assignment.submitter_type == "TEAM",
        Assignment.status.in_(["PUBLISHED", "CLOSED"]),
    ).order_by(Assignment.due_at.desc())).all()
    assignment_ids = [item.id for item in assignments]
    submissions = {item.assignment_id: item for item in db.scalars(select(Submission).where(Submission.assignment_id.in_(assignment_ids), Submission.owner_team_id == team_id)).all()}
    submitted = [item for item in submissions.values() if item.status == "SUBMITTED"]
    current_versions = {item.id: item.current_version_no for item in submitted}
    versions = {
        item.submission_id: item for item in db.scalars(select(SubmissionVersion).where(SubmissionVersion.submission_id.in_(current_versions))).all()
        if item.version_no == current_versions[item.submission_id]
    } if submitted else {}
    files_by_version: dict[UUID, list[FileObject]] = {}
    if versions:
        for version_id, file in db.execute(select(VersionFile.version_id, FileObject).join(FileObject, FileObject.id == VersionFile.file_id).where(VersionFile.version_id.in_([item.id for item in versions.values()]))):
            files_by_version.setdefault(version_id, []).append(file)

    def csv_bytes(rows: list[list]) -> bytes:
        output = io.StringIO()
        csv.writer(output).writerows([[export_cell(value) for value in row] for row in rows])
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    target = _temporary_zip()
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            written: set[tuple[str, UUID]] = set()
            homework_rows = [["作业", "截止时间", "提交状态", "提交时间", "是否迟交", "附件数"]]
            for assignment in assignments:
                submission = submissions.get(assignment.id)
                version = versions.get(submission.id) if submission else None
                files = files_by_version.get(version.id, []) if version else []
                homework_rows.append([assignment.title, assignment.due_at, "已提交" if version else "未提交", version.submitted_at if version else None, "是" if version and version.is_late else "否", len(files)])
                for file in files:
                    folder = f"小组作业/{assignment.id}"
                    _write_file(db, bundle, f"{folder}/{file.id}-{Path(file.original_name).name}", folder, file, written)
            bundle.writestr("小组作业提交记录.csv", csv_bytes(homework_rows))
            grade_rows = [["作业", "提交状态", "学生互评等级", "教师等级", "最终等级", "成绩来源", "评分状态"]]
            for assignment in assignments:
                submission = submissions.get(assignment.id)
                version = versions.get(submission.id) if submission else None
                result = displayed_submission_grade_result(db, version) if version else missing_submission_grade_result(assignment)
                grade_rows.append([assignment.title, "已提交" if version else "未提交", result["peer_grade"], result["teacher_grade"]["grade"] if result["teacher_grade"] else None, result["final_grade"], {"TEACHER": "教师评分", "PEER": "学生互评", "SYSTEM": "系统判定"}.get(result["grade_source"], ""), "已评分" if result["final_grade"] else "待评分"])
            bundle.writestr("小组作业成绩表.csv", csv_bytes(grade_rows))
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise
