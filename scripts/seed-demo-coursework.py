"""Create repeatable demo coursework submissions for 24 Computer Science Class 1.

Run from the repository root:
    .\\backend\\.venv\\Scripts\\python.exe .\\scripts\\seed-demo-coursework.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Assignment,
    FileObject,
    Submission,
    SubmissionVersion,
    Team,
    TeamMember,
    User,
    VersionFile,
)
from app.settings import settings  # noqa: E402


CLASS_NAMES = ("24计算机1", "24计算机1班")
PERSONAL_TITLE = "个人作业：需求分析报告（演示）"
TEAM_TITLE = "小组作业：课程项目方案（演示）"


def pdf_bytes(title: str) -> bytes:
    """Return a small valid one-page PDF using only built-in Python facilities."""
    content = f"BT /F1 18 Tf 72 720 Td ({title}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return bytes(data)


def write_submission_file(assignment: Assignment, owner: User, team: Team | None, name: str, content: bytes, mime: str) -> FileObject:
    file_id = uuid4()
    suffix = Path(name).suffix
    relative = f"{assignment.id}/{file_id.hex}{suffix}"
    target = settings.file_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return FileObject(
        id=file_id,
        owner_id=owner.id,
        assignment_id=assignment.id,
        team_id=team.id if team else None,
        purpose="SUBMISSION",
        storage_path=relative,
        original_name=name,
        size_bytes=len(content),
        detected_mime=mime,
        preview_status="READY",
    )


def member_snapshot(session, team: Team) -> dict:
    rows = session.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team.id, TeamMember.status == "ACTIVE")
        .order_by(User.login_name)
    ).all()
    return {
        "members": [
            {"id": str(user.id), "student_no": user.login_name, "name": user.display_name, "role": member.role}
            for member, user in rows
        ]
    }


def create_submission(session, assignment: Assignment, owner: User, team: Team | None, label: str, submitted_at: datetime) -> bool:
    existing = session.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.owner_team_id == team.id if team else Submission.owner_user_id == owner.id,
        )
    )
    if existing:
        return False

    submission = Submission(
        assignment_id=assignment.id,
        owner_user_id=None if team else owner.id,
        owner_team_id=team.id if team else None,
        status="SUBMITTED",
        current_version_no=1,
    )
    session.add(submission)
    session.flush()
    version = SubmissionVersion(
        submission_id=submission.id,
        version_no=1,
        submitted_by=owner.id,
        submitted_at=submitted_at,
        member_snapshot=member_snapshot(session, team) if team else {},
        is_late=False,
    )
    session.add(version)
    markdown = (
        f"# {assignment.title}\n\n"
        f"提交对象：{label}\n\n"
        "## 完成说明\n\n"
        "已完成需求梳理、方案设计与任务分工，并提交演示材料。\n"
    ).encode("utf-8")
    files = [
        write_submission_file(assignment, owner, team, f"{label}-作业说明.md", markdown, "text/markdown"),
        write_submission_file(assignment, owner, team, f"{label}-作业报告.pdf", pdf_bytes("Coursework demo report"), "application/pdf"),
    ]
    session.add_all(files)
    session.flush()
    session.add_all(VersionFile(version_id=version.id, file_id=file.id) for file in files)
    return True


def main() -> None:
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        # Select the existing target class by its display name, rather than creating a duplicate class.
        from app.models import TeachingClass  # kept local so the model list above stays submission-focused
        teaching_class = session.scalar(select(TeachingClass).where(TeachingClass.name.in_(CLASS_NAMES)))
        if not teaching_class:
            raise RuntimeError(f"未找到教学班：{' 或 '.join(CLASS_NAMES)}")

        teams = []
        for team in session.scalars(select(Team).where(Team.class_id == teaching_class.id, Team.status == "ACTIVE").order_by(Team.name)):
            if member_snapshot(session, team)["members"]:
                teams.append(team)
            if len(teams) == 2:
                break
        if len(teams) < 2:
            raise RuntimeError(f"{teaching_class.name} 至少需要两个包含成员的活动小组")

        personal = session.scalar(select(Assignment).where(Assignment.class_id == teaching_class.id, Assignment.title == PERSONAL_TITLE))
        if not personal:
            personal = Assignment(
                class_id=teaching_class.id,
                title=PERSONAL_TITLE,
                description="<p>请独立完成课程项目的需求分析，并提交 Markdown 说明和 PDF 报告。</p>",
                submitter_type="INDIVIDUAL",
                starts_at=now - timedelta(days=7),
                due_at=now + timedelta(days=14),
                allow_late=False,
                status="PUBLISHED",
            )
            session.add(personal)
            session.flush()

        team_assignment = session.scalar(select(Assignment).where(Assignment.class_id == teaching_class.id, Assignment.title == TEAM_TITLE))
        if not team_assignment:
            team_assignment = Assignment(
                class_id=teaching_class.id,
                title=TEAM_TITLE,
                description="<p>请以小组为单位完成课程项目方案，提交 Markdown 说明和 PDF 报告。</p>",
                submitter_type="TEAM",
                starts_at=now - timedelta(days=7),
                due_at=now + timedelta(days=14),
                allow_late=False,
                status="PUBLISHED",
            )
            session.add(team_assignment)
            session.flush()

        created_personal = 0
        created_team = 0
        for index, team in enumerate(teams, start=1):
            snapshot = member_snapshot(session, team)
            submitted_at = now - timedelta(days=2, hours=index)
            leader = session.get(User, team.leader_id)
            for item in snapshot["members"]:
                student = session.get(User, item["id"])
                created_personal += create_submission(session, personal, student, None, f"{team.name}-{student.display_name}", submitted_at)
            created_team += create_submission(session, team_assignment, leader, team, team.name, submitted_at)

    print(f"已处理 {teaching_class.name}：个人提交新增 {created_personal} 份，小组提交新增 {created_team} 份。")


if __name__ == "__main__":
    main()
