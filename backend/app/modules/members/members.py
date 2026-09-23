from __future__ import annotations

import csv
import io
import re
from fastapi import APIRouter, File, Response, UploadFile
from sqlalchemy import and_, delete, select
from uuid import UUID

from app.models import ClassMember, ImportBatch, LoginSession, Team, TeamMember, TeamRequest, User
from app.security import hash_password
from app.core.audit import audit, notify
from app.core.deps import CsrfUser, CurrentUser, Db, membership, require_class, require_writable_class, teacher
from app.core.errors import ApiError
from app.core.files import enqueue_archive_export
from app.core.utils import now
from app.modules.members.schemas import MemberCreateIn, MemberUpdateIn
from app.modules.members.service import member_detail, parse_roster

router = APIRouter()

@router.post("/api/v1/classes/{cid}/members/import-preview", status_code=201)
async def import_preview(cid: UUID, user: CsrfUser, db: Db, file: UploadFile = File(...)):
    teacher(user); require_writable_class(db, user, cid)
    try: raw = parse_roster(await file.read(), file.filename or "")
    except (UnicodeDecodeError, ValueError, IndexError): raise ApiError(422, "ROSTER_PARSE_FAILED", "无法读取名单，请确认列名为学号、姓名")
    seen, rows = set(), []
    for line, (sid, name) in enumerate(raw, 2):
        status, reason = "READY", "将创建账号"
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,32}", sid) or not name: status, reason = "ERROR", "学号或姓名格式错误"
        elif sid in seen: status, reason = "DUPLICATE", "文件内学号重复"
        else:
            old = db.scalar(select(User).where(User.login_name == sid))
            if old:
                existing_member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == old.id))
                status, reason = ("EXISTS", "已在当前教学班") if existing_member and existing_member.status == "ACTIVE" else ("JOIN", "加入已有账号")
        seen.add(sid); rows.append({"row": line, "student_no": sid, "name": name, "status": status, "reason": reason})
    batch = ImportBatch(class_id=cid, created_by=user.id, rows=rows); db.add(batch); db.commit()
    return {"batch_id": str(batch.id), "rows": rows, "summary": {s: sum(r["status"] == s for r in rows) for s in ["READY", "JOIN", "EXISTS", "DUPLICATE", "ERROR"]}}


@router.post("/api/v1/classes/{cid}/members/import/{bid}/confirm")
def import_confirm(cid: UUID, bid: UUID, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid); batch = db.scalar(select(ImportBatch).where(ImportBatch.id == bid, ImportBatch.class_id == cid).with_for_update())
    if not batch or batch.status != "PREVIEWED": raise ApiError(409, "IMPORT_NOT_CONFIRMABLE", "该导入批次已处理或不存在")
    created = joined = skipped = 0
    for row in batch.rows:
        if row["status"] not in {"READY", "JOIN"}: skipped += 1; continue
        student = db.scalar(select(User).where(User.login_name == row["student_no"]))
        if not student:
            student = User(login_name=row["student_no"], display_name=row["name"], password_hash=hash_password(row["student_no"]), role="STUDENT"); db.add(student); db.flush(); created += 1
        elif student.role != "STUDENT":
            row["status"], row["reason"] = "ERROR", "账号已被非学生用户使用"; skipped += 1; continue
        else:
            student.display_name = row["name"]
        existing_member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == student.id))
        if existing_member:
            if existing_member.status != "ACTIVE": existing_member.status = "ACTIVE"; joined += 1
        else: db.add(ClassMember(class_id=cid, user_id=student.id)); joined += 1
    batch.rows = [dict(row) for row in batch.rows]; batch.status = "CONFIRMED"; audit(db, user, "ROSTER_IMPORTED", "class", str(cid), {"created": created, "joined": joined, "skipped": skipped}); db.commit(); return {"created": created, "joined": joined, "skipped": skipped}


@router.get("/api/v1/classes/{cid}/members/import/{bid}/result.csv")
def import_result(cid: UUID, bid: UUID, user: CurrentUser, db: Db):
    teacher(user); require_class(db, user, cid)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.id == bid, ImportBatch.class_id == cid))
    if not batch: raise ApiError(404, "IMPORT_NOT_FOUND", "导入记录不存在")
    stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(["行号", "学号", "姓名", "状态", "结果"])
    for row in batch.rows: writer.writerow([row["row"], row["student_no"], row["name"], row["status"], row["reason"]])
    return Response(content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="roster-{bid}.csv"'})


@router.get("/api/v1/classes/{cid}/members")
def members(cid: UUID, user: CurrentUser, db: Db):
    require_class(db, user, cid)
    rows = db.execute(
        select(ClassMember, User, Team.name)
        .select_from(ClassMember)
        .join(User, User.id == ClassMember.user_id)
        .outerjoin(TeamMember, and_(TeamMember.class_id == cid, TeamMember.user_id == User.id, TeamMember.status == "ACTIVE"))
        .outerjoin(Team, and_(Team.id == TeamMember.team_id, Team.status == "ACTIVE"))
        .where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE")
        .order_by(User.login_name)
    ).all()
    items = [{"id": str(student.id), "student_no": student.login_name, "name": student.display_name, "status": member.status, "team": team_name, "joined_at": member.joined_at.isoformat()} for member, student, team_name in rows]
    return {"items": items, "total": len(items)}


@router.post("/api/v1/classes/{cid}/members", status_code=201)
def create_member(cid: UUID, data: MemberCreateIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    student_no, name = data.student_no.strip(), data.name.strip()
    if not name: raise ApiError(422, "MEMBER_NAME_REQUIRED", "请填写学生姓名")
    student = db.scalar(select(User).where(User.login_name == student_no).with_for_update())
    created = False
    if student and student.role != "STUDENT": raise ApiError(409, "ACCOUNT_CONFLICT", "该学号已被其他身份使用")
    if not student:
        student = User(login_name=student_no, display_name=name, password_hash=hash_password(student_no), role="STUDENT")
        db.add(student); db.flush(); created = True
    else:
        student.display_name = name
    class_member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == student.id).with_for_update())
    if class_member and class_member.status == "ACTIVE": raise ApiError(409, "MEMBER_EXISTS", "该学生已在当前教学班")
    if class_member: class_member.status = "ACTIVE"
    else: db.add(ClassMember(class_id=cid, user_id=student.id))
    audit(db, user, "CLASS_MEMBER_ADDED", "class", str(cid), {"user_id": str(student.id), "created_account": created}); db.commit()
    return member_detail(db, cid, student.id)[2]


@router.get("/api/v1/classes/{cid}/members/{uid}")
def get_member(cid: UUID, uid: UUID, user: CurrentUser, db: Db):
    require_class(db, user, cid)
    return member_detail(db, cid, uid)[2]


@router.patch("/api/v1/classes/{cid}/members/{uid}")
def update_member(cid: UUID, uid: UUID, data: MemberUpdateIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    _, student, _ = member_detail(db, cid, uid)
    name = data.name.strip()
    if not name: raise ApiError(422, "MEMBER_NAME_REQUIRED", "请填写学生姓名")
    old_name = student.display_name; student.display_name = name
    audit(db, user, "CLASS_MEMBER_UPDATED", "class", str(cid), {"user_id": str(uid), "old_name": old_name, "name": student.display_name}); db.commit()
    return member_detail(db, cid, uid)[2]


@router.get("/api/v1/classes/{cid}/members/{uid}/portfolio")
def student_portfolio(cid: UUID, uid: UUID, user: CurrentUser, db: Db):
    from app.student_portfolio import portfolio
    teacher(user); require_class(db, user, cid)
    return portfolio(db, cid, uid)


@router.post("/api/v1/classes/{cid}/members/{uid}/portfolio.zip", status_code=202)
def export_student_portfolio(cid: UUID, uid: UUID, user: CsrfUser, db: Db):
    from app.student_portfolio import safe_name

    teacher(user); require_class(db, user, cid)
    member = member_detail(db, cid, uid)[2]
    filename = f"{safe_name(member['student_no'])}_{safe_name(member['name'])}.zip"
    return enqueue_archive_export(
        db, user, "PORTFOLIO", {"class_id": str(cid), "student_id": str(uid)}, filename,
    )


@router.post("/api/v1/classes/{cid}/portfolio.zip", status_code=202)
def export_class_portfolio(cid: UUID, user: CsrfUser, db: Db):
    from app.student_portfolio import safe_name

    teacher(user); course = require_class(db, user, cid)
    return enqueue_archive_export(
        db, user, "PORTFOLIO", {"class_id": str(cid)}, f"{safe_name(course.name)}-班级档案.zip",
    )


@router.delete("/api/v1/classes/{cid}/members/{uid}", status_code=204)
def delete_member(cid: UUID, uid: UUID, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    class_member, student, _ = member_detail(db, cid, uid)
    team = membership(db, cid, uid)
    if team and team[1].leader_id == uid: raise ApiError(409, "TEAM_LEADER_TRANSFER_REQUIRED", "该学生是组长，请先移交组长或解散小组")
    if team:
        team[0].status = "REMOVED"; team[1].version += 1
    class_member.status = "REMOVED"
    db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == cid, TeamRequest.applicant_id == uid, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now()))
    notify(db, uid, "CLASS_MEMBER_REMOVED", "你已被移出教学班")
    audit(db, user, "CLASS_MEMBER_REMOVED", "class", str(cid), {"user_id": str(uid), "student_no": student.login_name}); db.commit()
    return Response(status_code=204)


@router.post("/api/v1/classes/{cid}/members/{uid}/reset-password", status_code=204)
def reset_password(cid: UUID, uid: UUID, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid); _, student, _ = member_detail(db, cid, uid)
    student.password_hash = hash_password(student.login_name)
    audit(db, user, "PASSWORD_RESET", "user", str(uid))
    db.execute(delete(LoginSession).where(LoginSession.user_id == uid))
    db.commit()
    return Response(status_code=204)
