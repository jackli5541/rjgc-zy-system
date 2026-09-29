import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.core.utils import now
from app.database import SessionLocal, engine
from app.main import app
from app.models import AiChatMessage, User
from app.modules.ai_teacher import router as ai_router
from app.settings import settings


def login(account, password, role):
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"account": account, "password": password, "role": role})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def assignment_fixture():
    teacher, teacher_headers = login("teacher", "123456", "teacher")
    course = teacher.post("/api/v1/classes", headers=teacher_headers, json={"semester": "AI 测试", "name": "AI 测试班"}).json()
    member = teacher.post(
        f"/api/v1/classes/{course['id']}/members", headers=teacher_headers,
        json={"student_no": "20990988", "name": "测试学生"},
    ).json()
    assignment = teacher.post("/api/v1/assignments", headers=teacher_headers, json={
        "class_id": course["id"], "title": "需求分析", "description": "分析系统需求与用例",
        "submitter_type": "INDIVIDUAL", "due_at": "2099-01-01T00:00:00+08:00", "publish": True,
    }).json()
    student, student_headers = login(member["student_no"], member["student_no"], "student")
    return teacher, student, student_headers, assignment["id"]


class FakeClient:
    async def stream_chat(self, messages):
        yield "需求分析"
        yield "应明确参与者。"


class FailingClient:
    async def stream_chat(self, messages):
        yield "部分回答"
        raise ai_router.AiClientError("上游中断")


def test_answer_review_requests_and_offers_are_not_returned(monkeypatch):
    monkeypatch.setattr(settings, "ai_teacher_enabled", True)
    _, student, headers, aid = assignment_fixture()
    path = f"/api/v1/assignments/{aid}/ai-teacher"
    conversation_id = str(uuid4())

    def no_model_call():
        raise AssertionError("Review requests must not call the model")

    monkeypatch.setattr(ai_router, "get_ai_client", no_model_call)
    review = student.post(f"{path}/chat", headers=headers, json={
        "question": "帮我检查已有的答案", "conversation_id": conversation_id,
    })
    assert "event: done" in review.text
    assert "我不能检查或评价" in review.text

    class OfferingClient:
        async def stream_chat(self, messages):
            yield "先列出参与者。想让我检"
            yield "查已有的答案？"

    monkeypatch.setattr(ai_router, "get_ai_client", lambda: OfferingClient())
    offered = student.post(f"{path}/chat", headers=headers, json={
        "question": "如何列出参与者", "conversation_id": conversation_id,
    })
    assert "event: done" in offered.text
    assert "想让我检查" not in offered.text
    history = student.get(f"{path}/history?conversation_id={conversation_id}").json()["messages"]
    assert len(history) == 4
    assert all("想让我检查" not in item["content"] for item in history)


def test_ai_teacher_schema_history_and_stream(monkeypatch):
    schema = inspect(engine)
    assert "conversation_id" in {column["name"] for column in schema.get_columns("ai_teacher_chat_messages")}
    assert {"embedding", "metadata"}.issubset({column["name"] for column in schema.get_columns("ai_teacher_knowledge_chunks")})
    monkeypatch.setattr(settings, "ai_teacher_enabled", True)
    monkeypatch.setattr(ai_router, "get_ai_client", lambda: FakeClient())
    teacher, student, headers, aid = assignment_fixture()
    first, second = str(uuid4()), str(uuid4())
    message_id = str(uuid4())
    path = f"/api/v1/assignments/{aid}/ai-teacher"

    assert teacher.get(f"{path}/history?conversation_id={first}").status_code == 403
    assert student.post(f"{path}/chat", json={"question": "如何分析需求", "conversation_id": first}).status_code == 403
    assert student.post(f"{path}/chat", headers=headers, json={
        "question": "今天天气如何", "conversation_id": first,
    }).status_code == 422
    assert student.post(f"{path}/chat", headers=headers, json={
        "question": "如何分析需求", "quote": "其他人的草稿", "conversation_id": first,
    }).status_code == 422

    response = student.post(f"{path}/chat", headers=headers, json={
        "question": "如何分析需求", "quote": "系统需求", "conversation_id": first, "message_id": message_id,
    })
    assert response.status_code == 200, response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text
    assert "event: error" not in response.text
    done = next(frame for frame in response.text.split("\n\n") if frame.startswith("event: done"))
    completed = json.loads(done.split("data: ", 1)[1])["messages"]
    assert [item["role"] for item in completed] == ["user", "assistant"]
    assert completed[0]["id"] == message_id
    assert completed[0]["created_at"] < completed[1]["created_at"]
    history = student.get(f"{path}/history?conversation_id={first}").json()["messages"]
    assert [item["id"] for item in history] == [item["id"] for item in completed]
    assert student.get(f"{path}/history?conversation_id={second}").json()["messages"] == []

    legacy_client = student.post(f"{path}/chat", headers=headers, json={
        "question": "怎样写用例", "conversation_id": second,
    })
    assert "event: done" in legacy_client.text
    assert [item["role"] for item in student.get(f"{path}/history?conversation_id={second}").json()["messages"]] == ["user", "assistant"]

    monkeypatch.setattr(ai_router, "get_ai_client", lambda: FailingClient())
    failed_conversation = str(uuid4())
    failed = student.post(f"{path}/chat", headers=headers, json={
        "question": "怎样写用例", "conversation_id": failed_conversation,
    })
    assert "event: error" in failed.text
    assert student.get(f"{path}/history?conversation_id={failed_conversation}").json()["messages"] == []

    legacy_conversation = str(uuid4())
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.login_name == "20990988"))
        same_time = now()
        db.add_all([
            AiChatMessage(assignment_id=UUID(aid), student_id=user_id, conversation_id=UUID(legacy_conversation), role="assistant", content="旧回答", contexts=[], created_at=same_time),
            AiChatMessage(assignment_id=UUID(aid), student_id=user_id, conversation_id=UUID(legacy_conversation), role="user", content="旧问题", contexts=[], created_at=same_time),
        ])
        db.commit()
    legacy_history = student.get(f"{path}/history?conversation_id={legacy_conversation}").json()["messages"]
    assert [item["role"] for item in legacy_history] == ["user", "assistant"]


def test_workspace_quote_does_not_require_saved_document(monkeypatch):
    monkeypatch.setattr(settings, "ai_teacher_enabled", True)
    monkeypatch.setattr(ai_router, "get_ai_client", lambda: FakeClient())
    _, student, headers, aid = assignment_fixture()
    path = f"/api/v1/assignments/{aid}"
    conversation_id = str(uuid4())
    quote = "这段是尚未保存的 Markdown 编辑器选区"

    missing = student.post(f"{path}/ai-teacher/chat", headers=headers, json={
        "question": "怎样理解参与者", "quote": quote, "quote_source": "workspace", "conversation_id": conversation_id,
    })
    assert missing.status_code == 422
    assert missing.json()["code"] == "QUOTE_OUT_OF_SCOPE"

    workspace = student.post(f"{path}/workspace", headers=headers)
    assert workspace.status_code == 200
    response = student.post(f"{path}/ai-teacher/chat", headers=headers, json={
        "question": "怎样理解参与者", "quote": quote, "quote_source": "workspace", "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    assert "event: done" in response.text
    history = student.get(f"{path}/ai-teacher/history?conversation_id={conversation_id}").json()["messages"]
    assert history[0]["contexts"] == [{"quote": quote}]

    invalid_assignment_quote = student.post(f"{path}/ai-teacher/chat", headers=headers, json={
        "question": "怎样理解参与者", "quote": quote, "quote_source": "assignment", "conversation_id": str(uuid4()),
    })
    assert invalid_assignment_quote.status_code == 422
    assert student.post(f"{path}/ai-teacher/chat", headers=headers, json={
        "question": "怎样理解参与者", "quote": "x" * (settings.ai_teacher_max_quote_chars + 1),
        "quote_source": "workspace", "conversation_id": str(uuid4()),
    }).status_code == 422


def test_ai_teacher_done_serialization_failure_does_not_commit(monkeypatch):
    monkeypatch.setattr(settings, "ai_teacher_enabled", True)
    monkeypatch.setattr(ai_router, "get_ai_client", lambda: FakeClient())
    original_sse = ai_router.sse

    def fail_done(event, data):
        if event == "done":
            raise TypeError("serialization failed")
        return original_sse(event, data)

    monkeypatch.setattr(ai_router, "sse", fail_done)
    _, student, headers, aid = assignment_fixture()
    conversation_id = str(uuid4())
    path = f"/api/v1/assignments/{aid}/ai-teacher"
    response = student.post(f"{path}/chat", headers=headers, json={
        "question": "如何分析需求", "conversation_id": conversation_id,
    })
    assert "event: error" in response.text
    assert "event: done" not in response.text
    assert student.get(f"{path}/history?conversation_id={conversation_id}").json()["messages"] == []


def test_ai_teacher_worker_limit():
    student = uuid4()
    ai_router.reserve_student(student)
    try:
        from app.core.errors import ApiError

        try:
            ai_router.reserve_student(student)
            assert False, "a student must not have concurrent generations"
        except ApiError as exc:
            assert exc.status == 429
    finally:
        ai_router.release_student(student)


def test_ai_teacher_cross_worker_lock():
    from app.core.errors import ApiError

    student = uuid4()
    connection, resource = ai_router.lock_student_across_workers(student)
    try:
        try:
            ai_router.lock_student_across_workers(student)
            assert False, "the same student must be locked across worker connections"
        except ApiError as exc:
            assert exc.status == 429
    finally:
        ai_router.unlock_student_across_workers(connection, resource)
