from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import AiGradingDraft, BackgroundJob, SubmissionAssessment


def login(account, password, role):
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"account": account, "password": password, "role": role})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def test_single_ai_grading_is_explicit_permission_checked_and_does_not_publish():
    teacher, headers = login("teacher", "123456", "teacher")
    course = teacher.post("/api/v1/classes", headers=headers, json={"semester": "AI 批改测试", "name": "单份批改"}).json()
    student_no = "ai" + uuid4().hex[:12]
    member = teacher.post(f"/api/v1/classes/{course['id']}/members", headers=headers, json={"student_no": student_no, "name": "批改测试学生"})
    assert member.status_code == 201, member.text
    student, student_headers = login(student_no, student_no, "student")
    response = teacher.post("/api/v1/assignments", headers=headers, json={
        "class_id": course["id"], "title": "单份批改", "description": "检查需求分析",
        "submitter_type": "INDIVIDUAL", "due_at": "2099-01-01T00:00:00+08:00", "publish": True,
    })
    assert response.status_code == 201, response.text
    aid = response.json()["id"]
    uploaded = student.post(f"/api/v1/assignments/{aid}/files", headers=student_headers, files={"file": ("answer.md", b"# Answer", "text/markdown")})
    assert uploaded.status_code == 201, uploaded.text
    submitted = student.post(f"/api/v1/assignments/{aid}/submission", headers={**student_headers, "Idempotency-Key": str(uuid4())}, json={"file_ids": [uploaded.json()["id"]]})
    assert submitted.status_code == 201, submitted.text
    board = teacher.get(f"/api/v1/assignments/{aid}/submissions").json()["items"]
    version_id = next(item["submission_version_id"] for item in board if item.get("student_no") == student_no)
    path = f"/api/v1/assignments/{aid}/submissions/{version_id}/ai-grading-draft"
    assert teacher.get(path).json() == {"draft": None}
    assert student.post(path + "/retry", headers=student_headers).status_code == 403
    assert teacher.post(path + "/retry").status_code == 403
    invalid = teacher.post(f"/api/v1/assignments/{aid}/submissions/{uuid4()}/ai-grading-draft/retry", headers=headers)
    assert invalid.status_code == 409

    missing = teacher.post(path + "/retry", headers=headers)
    assert missing.status_code == 422 and missing.json()["code"] == "AI_GRADING_CRITERIA_REQUIRED"
    criteria = teacher.post(f"/api/v1/assignments/{aid}/files?material_type=CRITERIA", headers=headers, files={"file": ("criteria.md", "A：需求完整；B：少量遗漏；C：部分完成；D：重大缺陷；E：未完成".encode(), "text/markdown")})
    assert criteria.status_code == 201, criteria.text

    started = teacher.post(path + "/retry", headers=headers)
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "PROCESSING"
    assert started.json()["phase"] == "QUEUED"
    draft_id = UUID(started.json()["id"])
    duplicate = teacher.post(path + "/retry", headers=headers)
    assert duplicate.status_code == 202 and duplicate.json()["id"] == str(draft_id)
    with SessionLocal.begin() as db:
        jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.kind == "AI_GRADING_DRAFT")).all()
        assert sum(job.payload.get("draft_id") == str(draft_id) for job in jobs) == 1
        assert all(job.status == "AI_PENDING" for job in jobs if job.payload.get("draft_id") == str(draft_id))
        assert db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == UUID(version_id))) is None
        draft = db.get(AiGradingDraft, draft_id)
        draft.status = "READY"
        draft.suggested_grade = "A"
        draft.suggested_comment = "需求完整"
    ready = teacher.get(path).json()["draft"]
    assert ready["status"] == "READY" and ready["suggested_grade"] == "A"
    with SessionLocal() as db:
        assert db.scalar(select(SubmissionAssessment.id).where(SubmissionAssessment.submission_version_id == UUID(version_id))) is None

    published = teacher.post(f"/api/v1/submission-versions/{version_id}/feedback/publish", headers=headers, json={"revision": 0, "grade": "A", "comment": "需求完整", "annotations": []})
    assert published.status_code == 200, published.text
    assert teacher.post(path + "/retry", headers=headers).status_code == 409
