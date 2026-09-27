from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from io import BytesIO
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest
from sqlalchemy import select

from app.core.utils import now
from app.database import SessionLocal
from app.main import app
from app.models import AttendanceRecord, AttendanceSession
from app.modules.attendance import service as attendance_service
from app.modules.attendance.service import code_valid, current_code, process_due_attendance


def login(account, password, role):
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"account": account, "password": password, "role": role})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def setup_class():
    teacher, teacher_headers = login("teacher", "123456", "teacher")
    course = teacher.post("/api/v1/classes", headers=teacher_headers, json={"semester": "2026秋", "name": "考勤测试班"}).json()
    member = teacher.post(f"/api/v1/classes/{course['id']}/members", headers=teacher_headers, json={"student_no": "20990999", "name": "签到学生"}).json()
    student, student_headers = login(member["student_no"], member["student_no"], "student")
    return teacher, teacher_headers, student, student_headers, course, member


def start(teacher, headers, class_id, title):
    response = teacher.post(f"/api/v1/classes/{class_id}/attendance-sessions", headers=headers, json={"title": title, "duration_minutes": 15})
    assert response.status_code == 201, response.text
    return response.json()


def test_scheduled_attendance_starts_at_selected_time():
    teacher, teacher_headers, student, student_headers, course, _ = setup_class()
    path = f"/api/v1/classes/{course['id']}/attendance-sessions"
    planned = now() + timedelta(minutes=5)
    response = teacher.post(path, headers=teacher_headers, json={"title": "预约考勤", "duration_minutes": 15, "started_at": planned.isoformat()})
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["status"] == "SCHEDULED"
    assert "code" not in session
    assert datetime.fromisoformat(session["started_at"]) == planned
    assert datetime.fromisoformat(session["expires_at"]) == planned + timedelta(minutes=15)
    assert teacher.get(f"/api/v1/attendance-sessions/{session['id']}/code").json().get("code") is None
    assert student.get(f"/api/v1/classes/{course['id']}/attendance/current").json()["active"] is None
    assert student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": "000000"}).status_code == 409
    assert teacher.post(path, headers=teacher_headers, json={"title": "冲突", "duration_minutes": 15}).status_code == 409

    with SessionLocal() as db:
        item = db.get(AttendanceSession, UUID(session["id"]))
        item.started_at = now() - timedelta(seconds=1)
        db.commit()
    active = teacher.get(f"/api/v1/attendance-sessions/{session['id']}/code").json()
    assert active["status"] == "ACTIVE" and "code" in active
    assert student.get(f"/api/v1/classes/{course['id']}/attendance/current").json()["active"]["id"] == session["id"]
    assert student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": active["code"]}).status_code == 200


def test_scheduled_attendance_rejects_invalid_start_time():
    teacher, headers, _, _, course, _ = setup_class()
    path = f"/api/v1/classes/{course['id']}/attendance-sessions"
    for started_at in ((now() + timedelta(minutes=5)).replace(tzinfo=None).isoformat(), (now() - timedelta(minutes=5)).isoformat()):
        response = teacher.post(path, headers=headers, json={"title": "无效时间", "started_at": started_at})
        assert response.status_code == 422
    assert teacher.get(path).json()["items"] == []


def test_attendance_check_in_correction_export_and_deduction():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    class_id = course["id"]
    assert "attendance" in teacher.get("/api/v1/menu-permissions").json()["enabled"]
    assert "attendance" not in student.get("/api/v1/menu-permissions").json()["enabled"]
    first = start(teacher, teacher_headers, class_id, "第一次")
    assert first["total"] == 1
    assert teacher.get(f"/api/v1/classes/{class_id}/attendance-sessions").json()["items"][0]["pending"] == 1
    assert student.get(f"/api/v1/classes/{class_id}/attendance/current").json()["active"]["id"] == first["id"]
    assert student.get(f"/api/v1/attendance-sessions/{first['id']}").status_code == 403
    assert student.post(f"/api/v1/attendance-sessions/{first['id']}/check-in", json={"code": first["code"]}).status_code == 403
    code = teacher.get(f"/api/v1/attendance-sessions/{first['id']}/code").json()["code"]
    signed = student.post(f"/api/v1/attendance-sessions/{first['id']}/check-in", headers=student_headers, json={"code": code})
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "PRESENT"
    assert teacher.get(f"/api/v1/classes/{class_id}/attendance-sessions").json()["items"][0]["present"] == 1
    assert student.post(f"/api/v1/attendance-sessions/{first['id']}/check-in", headers=student_headers, json={"code": "000000"}).json()["status"] == "PRESENT"
    assert teacher.post(f"/api/v1/attendance-sessions/{first['id']}/end", headers=teacher_headers).status_code == 200

    second = start(teacher, teacher_headers, class_id, "第二次")
    with SessionLocal() as db:
        session = db.get(AttendanceSession, UUID(second["id"]))
        session.started_at = now() - timedelta(minutes=11)
        db.commit()
    code = teacher.get(f"/api/v1/attendance-sessions/{second['id']}/code").json()["code"]
    signed = student.post(f"/api/v1/attendance-sessions/{second['id']}/check-in", headers=student_headers, json={"code": code})
    assert signed.status_code == 200 and signed.json()["status"] == "PRESENT"
    late = teacher.put(f"/api/v1/attendance-sessions/{second['id']}/records/{member['id']}", headers=teacher_headers, json={"status": "LATE"})
    assert late.status_code == 200 and late.json()["status"] == "LATE"
    teacher.post(f"/api/v1/attendance-sessions/{second['id']}/end", headers=teacher_headers)

    third = start(teacher, teacher_headers, class_id, "第三次")
    teacher.post(f"/api/v1/attendance-sessions/{third['id']}/end", headers=teacher_headers)
    grade = teacher.get(f"/api/v1/classes/{class_id}/grade-overview").json()["items"][0]
    assert grade["attendance_component"] == 8.5

    corrected = teacher.put(f"/api/v1/attendance-sessions/{third['id']}/records/{member['id']}", headers=teacher_headers, json={"status": "LEAVE", "note": "事假"})
    assert corrected.status_code == 200, corrected.text
    assert teacher.get(f"/api/v1/classes/{class_id}/grade-overview").json()["items"][0]["attendance_component"] == 9.5
    exported = teacher.get(f"/api/v1/classes/{class_id}/attendance.xlsx")
    assert exported.status_code == 200
    sheet = load_workbook(BytesIO(exported.content), read_only=True).active
    assert list(sheet.values)[1][-5:] == ("出勤", "迟到", "请假", "缺勤", "考勤分")
    assert list(sheet.values)[2][-5:] == (1, 1, 1, 0, 9.5)
    for number in range(10):
        extra = start(teacher, teacher_headers, class_id, f"补充场次{number + 1}")
        teacher.post(f"/api/v1/attendance-sessions/{extra['id']}/end", headers=teacher_headers)
    assert teacher.get(f"/api/v1/classes/{class_id}/grade-overview").json()["items"][0]["attendance_component"] == 0


def test_attendance_code_limit_and_closed_session():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    class_id = course["id"]
    session = start(teacher, teacher_headers, class_id, "限流测试")
    assert teacher.post(f"/api/v1/classes/{class_id}/attendance-sessions", headers=teacher_headers, json={"title": "重复场次", "duration_minutes": 15}).status_code == 409
    wrong = "000000" if session["code"] != "000000" else "111111"
    for _ in range(5):
        assert student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": wrong}).status_code == 422
    assert student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": session["code"]}).status_code == 429
    teacher.post(f"/api/v1/attendance-sessions/{session['id']}/end", headers=teacher_headers)
    assert student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": session["code"]}).status_code == 409
    manual = start(teacher, teacher_headers, class_id, "教师确认")
    teacher.put(f"/api/v1/attendance-sessions/{manual['id']}/records/{member['id']}", headers=teacher_headers, json={"status": "ABSENT", "note": "现场核实"})
    assert student.post(f"/api/v1/attendance-sessions/{manual['id']}/check-in", headers=student_headers, json={"code": manual["code"]}).status_code == 409


def test_expired_attendance_becomes_absent_and_can_be_corrected():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    class_id = course["id"]
    session = start(teacher, teacher_headers, class_id, "到期考勤")
    before = teacher.get(f"/api/v1/attendance-sessions/{session['id']}").json()
    assert before["status"] == "ACTIVE"
    assert before["records"][0]["status"] == "PENDING"
    with SessionLocal() as db:
        item = db.get(AttendanceSession, UUID(session["id"]))
        item.expires_at = now() - timedelta(seconds=1)
        db.commit()
    with SessionLocal.begin() as db:
        assert process_due_attendance(db, now()) == 1
    after = teacher.get(f"/api/v1/attendance-sessions/{session['id']}").json()
    assert after["status"] == "ENDED"
    assert after["absent"] == 1 and after["pending"] == 0
    assert after["records"][0]["status"] == "ABSENT"
    assert student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": session["code"]}).status_code == 409
    assert teacher.get(f"/api/v1/classes/{class_id}/grade-overview").json()["items"][0]["attendance_component"] == 9
    corrected = teacher.put(f"/api/v1/attendance-sessions/{session['id']}/records/{member['id']}", headers=teacher_headers, json={"status": "LATE", "note": "现场核实"})
    assert corrected.status_code == 200 and corrected.json()["status"] == "LATE"
    assert teacher.get(f"/api/v1/classes/{class_id}/grade-overview").json()["items"][0]["attendance_component"] == 9.5
    corrected = teacher.put(f"/api/v1/attendance-sessions/{session['id']}/records/{member['id']}", headers=teacher_headers, json={"status": "PRESENT", "note": "补签"})
    assert corrected.status_code == 200 and corrected.json()["status"] == "PRESENT"
    assert teacher.get(f"/api/v1/classes/{class_id}/grade-overview").json()["items"][0]["attendance_component"] == 10


def test_active_legacy_absence_is_pending_and_can_check_in():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    session = start(teacher, teacher_headers, course["id"], "进行中考勤")
    with SessionLocal() as db:
        record = db.query(AttendanceRecord).filter_by(session_id=UUID(session["id"])).one()
        record.status = "ABSENT"
        db.commit()
    current = student.get(f"/api/v1/classes/{course['id']}/attendance/current").json()
    assert current["active"]["record"]["status"] == "PENDING"
    assert current["recent"][0]["record"]["status"] == "PENDING"
    with SessionLocal() as db:
        record = db.query(AttendanceRecord).filter_by(session_id=UUID(session["id"])).one()
        record.status = "ABSENT"
        db.commit()
    code = teacher.get(f"/api/v1/attendance-sessions/{session['id']}/code").json()["code"]
    signed = student.post(f"/api/v1/attendance-sessions/{session['id']}/check-in", headers=student_headers, json={"code": code})
    assert signed.status_code == 200 and signed.json()["status"] == "PRESENT"


def test_teacher_can_delete_attendance_session_and_its_scores():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    class_id = course["id"]
    active = start(teacher, teacher_headers, class_id, "误发场次")
    path = f"/api/v1/attendance-sessions/{active['id']}"
    assert student.delete(path, headers=student_headers).status_code == 403
    assert teacher.delete(path).status_code == 403
    assert teacher.delete(path, headers=teacher_headers).status_code == 204
    assert teacher.get(path).status_code == 404
    assert teacher.get(f"/api/v1/classes/{class_id}/attendance-sessions").json()["items"] == []
    assert student.get(f"/api/v1/classes/{class_id}/attendance/current").json()["active"] is None

    ended = start(teacher, teacher_headers, class_id, "待删除场次")
    teacher.post(f"/api/v1/attendance-sessions/{ended['id']}/end", headers=teacher_headers)
    grades_path = f"/api/v1/classes/{class_id}/grade-overview"
    assert teacher.get(grades_path).json()["items"][0]["attendance_component"] == 9
    assert teacher.delete(f"/api/v1/attendance-sessions/{ended['id']}", headers=teacher_headers).status_code == 204
    assert teacher.get(grades_path).json()["items"][0]["attendance_component"] is None
    assert teacher.get(f"/api/v1/classes/{class_id}/attendance-sessions").json()["items"] == []


def test_previous_code_has_five_second_grace_period():
    session = SimpleNamespace(code_secret=b"attendance-code-test-secret-1234")
    boundary = datetime.fromtimestamp(30_000_000, timezone.utc)
    previous_code = current_code(session, boundary - timedelta(seconds=1))
    assert previous_code != current_code(session, boundary)
    assert code_valid(session, previous_code, boundary + timedelta(seconds=4))
    assert not code_valid(session, previous_code, boundary + timedelta(seconds=5))


def test_check_in_does_not_wait_for_session_update_lock():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    session = start(teacher, teacher_headers, course["id"], "锁兼容考勤")
    code = teacher.get(f"/api/v1/attendance-sessions/{session['id']}/code").json()["code"]
    with SessionLocal() as db:
        db.scalar(select(AttendanceSession).where(AttendanceSession.id == UUID(session["id"])).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                student.post,
                f"/api/v1/attendance-sessions/{session['id']}/check-in",
                headers=student_headers,
                json={"code": code},
            )
            try:
                response = future.result(timeout=5)
            finally:
                db.rollback()
    assert response.status_code == 200, response.text


def test_ending_attendance_waits_for_shared_session_lock():
    teacher, teacher_headers, student, student_headers, course, member = setup_class()
    session = start(teacher, teacher_headers, course["id"], "结束竞态考勤")
    with SessionLocal() as db:
        db.scalar(
            select(AttendanceSession)
            .where(AttendanceSession.id == UUID(session["id"]))
            .with_hint(AttendanceSession, "WITH (HOLDLOCK, ROWLOCK)", dialect_name="mssql")
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                teacher.post,
                f"/api/v1/attendance-sessions/{session['id']}/end",
                headers=teacher_headers,
            )
            try:
                with pytest.raises(FutureTimeoutError):
                    future.result(timeout=0.5)
            finally:
                db.rollback()
            response = future.result(timeout=5)
    assert response.status_code == 200, response.text
    detail = teacher.get(f"/api/v1/attendance-sessions/{session['id']}").json()
    assert detail["status"] == "ENDED" and detail["absent"] == 1


def test_fifty_students_can_check_in_concurrently(monkeypatch):
    teacher, teacher_headers, first_student, first_headers, course, first_member = setup_class()
    students = [(first_student, first_headers)]
    for index in range(49):
        response = teacher.post(
            f"/api/v1/classes/{course['id']}/members",
            headers=teacher_headers,
            json={"student_no": f"20991{index:03d}", "name": f"并发学生{index + 2}"},
        )
        assert response.status_code == 201, response.text
        student_no = response.json()["student_no"]
        students.append(login(student_no, student_no, "student"))

    monkeypatch.setattr(attendance_service, "CODE_PERIOD_SECONDS", 300)
    session = start(teacher, teacher_headers, course["id"], "并发考勤")
    code = teacher.get(f"/api/v1/attendance-sessions/{session['id']}/code").json()["code"]
    barrier = Barrier(len(students))

    def sign_in(client, headers):
        barrier.wait(timeout=30)
        return client.post(
            f"/api/v1/attendance-sessions/{session['id']}/check-in",
            headers=headers,
            json={"code": code},
        )

    with ThreadPoolExecutor(max_workers=len(students)) as executor:
        responses = list(executor.map(lambda pair: sign_in(*pair), students))

    assert [response.status_code for response in responses] == [200] * len(students), [response.text for response in responses if response.status_code != 200]
    detail = teacher.get(f"/api/v1/attendance-sessions/{session['id']}").json()
    assert detail["total"] == detail["present"] == 50
    assert len({record["student_id"] for record in detail["records"]}) == 50
