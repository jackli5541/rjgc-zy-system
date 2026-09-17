from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Assignment, AuditLog, FileObject, Submission, SubmissionAssessment, SubmissionVersion
from app.student_portfolio import safe_name
from test_api import login


def test_student_portfolio_and_archives():
    teacher, headers = login("teacher", "123456", "teacher")
    course = teacher.post("/api/v1/classes", headers=headers, json={"semester": "2039 秋季", "name": "档案导出班"}).json()
    cid = course["id"]
    member = teacher.post(f"/api/v1/classes/{cid}/members", headers=headers, json={"student_no": "20390001", "name": "=SUM(1,2)"}).json()
    removed = teacher.post(f"/api/v1/classes/{cid}/members", headers=headers, json={"student_no": "20390002", "name": "移出学生"}).json()
    student, student_headers = login("20390001", "20390001", "student")
    student.post("/api/v1/teams", headers=student_headers, json={"class_id": cid, "name": "档案组"})
    assignment = teacher.post("/api/v1/assignments", headers=headers, json={"class_id": cid, "title": "个人报告", "description": "报告", "submitter_type": "INDIVIDUAL", "due_at": "2099-01-01T00:00:00+08:00"}).json()
    other = teacher.post("/api/v1/assignments", headers=headers, json={"class_id": cid, "title": "未交作业", "description": "报告", "submitter_type": "INDIVIDUAL", "due_at": "2099-01-02T00:00:00+08:00"}).json()
    teacher.post("/api/v1/assignments", headers=headers, json={"class_id": cid, "title": "小组报告", "description": "报告", "submitter_type": "TEAM", "due_at": "2099-01-01T00:00:00+08:00"})
    files = []
    for content in [b"one", b"two"]:
        response = student.post(f"/api/v1/assignments/{assignment['id']}/files", headers=student_headers, files={"file": ("report.pdf", content, "application/pdf")})
        assert response.status_code == 201, response.text
        files.append(response.json())
    assert student.post(f"/api/v1/assignments/{assignment['id']}/submission", headers={**student_headers, "Idempotency-Key": "portfolio-current"}, json={}).status_code == 201
    teacher.post(f"/api/v1/assignments/{assignment['id']}/submissions/{member['id']}/grade", headers=headers, json={"grade": "B", "comment": "<p><strong>完整</strong><br>继续保持</p>"})
    with SessionLocal() as db:
        db.get(Assignment, UUID(other["id"])).due_at = datetime.now(UTC) - timedelta(days=1)
        version = db.scalar(select(SubmissionVersion).join(Submission).where(Submission.assignment_id == UUID(assignment['id'])))
        db.add(SubmissionAssessment(assignment_id=UUID(assignment["id"]), submission_version_id=version.id, evaluator_id=UUID(removed["id"]), subject_user_id=UUID(member["id"]), kind="PEER", grade="A", comment="<p>结构<strong>清晰</strong></p>", status="PUBLISHED"))
        db.commit()
    base = f"/api/v1/classes/{cid}/members/{member['id']}/portfolio"
    data = teacher.get(base).json()
    assert data["summary"] == {"total": 2, "submitted": 1, "late": 0, "missing": 1}
    submitted = next(item for item in data["assignments"] if item["status"] == "SUBMITTED")
    assert submitted["final_grade"] == "B" and submitted["peer_grade"] == "A"
    assert len(submitted["received_reviews"]) == 1
    assert next(item for item in data["assignments"] if item["status"] != "SUBMITTED")["grade_source"] == "SYSTEM"
    assert student.get(base).status_code == 403
    assert student.get(base + ".zip").status_code == 403
    assert TestClient(app).get(base).status_code == 401
    another = teacher.post("/api/v1/classes", headers=headers, json={"semester": "2039 秋季", "name": "另一班"}).json()
    assert teacher.get(f"/api/v1/classes/{another['id']}/members/{member['id']}/portfolio").status_code == 404
    response = teacher.get(base + ".zip")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 3
        assert len(set(archive.namelist())) == 3
        workbook = load_workbook(BytesIO(archive.read("学生档案.xlsx")))
        assert workbook.sheetnames == ["基本信息", "作业记录", "收到的互评"]
        assert workbook["基本信息"]["B2"].data_type == "s"
        assert workbook["作业记录"].max_row == 3
        assignment_headers = [cell.value for cell in workbook["作业记录"][1]]
        assert assignment_headers == ["作业", "截止时间", "提交状态", "提交时间", "提交版本", "迟交", "附件", "互评成绩", "教师评分", "最终成绩", "成绩来源", "评分状态", "教师评语"]
        assignment_row = next(row for row in workbook["作业记录"].iter_rows(min_row=2) if row[0].value == "个人报告")
        assert assignment_row[7].value == "A"
        assert assignment_row[8].value == "B"
        assert assignment_row[9].value == "B"
        assert assignment_row[12].value == "完整\n继续保持"
        assert workbook["收到的互评"]["D2"].value == "结构清晰"
        assert all("<" not in str(cell.value or "") for sheet in workbook for row in sheet for cell in row)
    assert teacher.delete(f"/api/v1/classes/{cid}/members/{removed['id']}", headers=headers).status_code == 204
    response = teacher.get(f"/api/v1/classes/{cid}/portfolio.zip")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        assert all(name.startswith("20390001_") for name in archive.namelist())
        assert sum(name.endswith("/report.pdf") or "/report (" in name for name in archive.namelist()) == 2
        assert any(name.endswith("/学生档案.xlsx") for name in archive.namelist())
    for file in files:
        assert student.delete(f"/api/v1/files/{file['id']}", headers=student_headers).status_code == 204
    replacement = student.post(f"/api/v1/assignments/{assignment['id']}/files", headers=student_headers, files={"file": ("updated.pdf", b"updated", "application/pdf")}).json()
    assert student.post(f"/api/v1/assignments/{assignment['id']}/submission", headers={**student_headers, "Idempotency-Key": "portfolio-v2"}, json={}).status_code == 201
    updated = teacher.get(base).json()
    current = next(item for item in updated["assignments"] if item["status"] == "SUBMITTED")
    assert current["version_no"] == 2 and current["final_grade"] is None
    assert current["received_reviews"] == []
    with ZipFile(BytesIO(teacher.get(base + ".zip").content)) as archive:
        assert len(archive.namelist()) == 2
        assert any(name.endswith("/updated.pdf") for name in archive.namelist())
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "STUDENT_PORTFOLIOS_EXPORTED"))
        db.get(FileObject, UUID(replacement["id"])).storage_path = "missing-portfolio.pdf"
        db.commit()
    failed = teacher.get(base + ".zip")
    assert failed.status_code == 404 and failed.json()["code"] == "FILE_MISSING"


def test_portfolio_filename_safety():
    assert "/" not in safe_name("../../report.pdf")
    assert "\\" not in safe_name("..\\report.pdf")
    assert safe_name("CON.pdf") == "_CON.pdf"
    assert safe_name("...") == "unnamed"
