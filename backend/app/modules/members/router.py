from __future__ import annotations

import secrets
from fastapi import APIRouter, Query, Response
from sqlalchemy import delete, func, select
from typing import Literal
from uuid import UUID

from app.models import Assignment, ClassJoinRequest, ClassMember, ImportBatch, TeachingClass, Team, User
from app.core.audit import audit
from app.core.deps import CsrfUser, CurrentUser, Db, membership, require_class, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.utils import now
from app.modules.members.schemas import ClassIn, ClassJoinIn, ClassUpdateIn
from app.modules.members.service import class_json

router = APIRouter()

@router.get("/api/v1/classes")
def classes(user: CurrentUser, db: Db):
    q = select(TeachingClass).where(TeachingClass.teacher_id == user.id) if user.role == "TEACHER" else select(TeachingClass).join(ClassMember).where(ClassMember.user_id == user.id, ClassMember.status == "ACTIVE")
    courses = db.scalars(q.order_by(
        TeachingClass.semester.desc(),
        TeachingClass.name.asc(),
        TeachingClass.created_at.desc(),
        TeachingClass.id.desc(),
    )).all()
    if not courses: return {"items": [], "total": 0}
    class_ids = [x.id for x in courses]
    member_counts = dict(db.execute(select(ClassMember.class_id, func.count()).where(ClassMember.class_id.in_(class_ids), ClassMember.status == "ACTIVE").group_by(ClassMember.class_id)).all())
    assignment_counts = dict(db.execute(select(Assignment.class_id, func.count()).where(Assignment.class_id.in_(class_ids)).group_by(Assignment.class_id)).all())
    if user.role == "STUDENT":
        items = [class_json(x, member_count=member_counts.get(x.id, 0), assignment_count=assignment_counts.get(x.id, 0), deletable=False) for x in courses]
        return {"items": items, "total": len(items)}
    member_history_counts = dict(db.execute(select(ClassMember.class_id, func.count()).where(ClassMember.class_id.in_(class_ids)).group_by(ClassMember.class_id)).all())
    import_counts = dict(db.execute(select(ImportBatch.class_id, func.count()).where(ImportBatch.class_id.in_(class_ids)).group_by(ImportBatch.class_id)).all())
    team_counts = dict(db.execute(select(Team.class_id, func.count()).where(Team.class_id.in_(class_ids)).group_by(Team.class_id)).all())
    items = [class_json(x, member_count=member_counts.get(x.id, 0), assignment_count=assignment_counts.get(x.id, 0), deletable=not any((member_history_counts.get(x.id, 0), assignment_counts.get(x.id, 0), import_counts.get(x.id, 0), team_counts.get(x.id, 0)))) for x in courses]
    return {"items": items, "total": len(items)}


@router.post("/api/v1/classes", status_code=201)
def create_class(data: ClassIn, user: CsrfUser, db: Db):
    teacher(user); x = TeachingClass(teacher_id=user.id, semester=data.semester.strip(), name=data.name.strip(), invite_code=secrets.token_hex(4).upper(), team_deadline=data.team_deadline, topic_public=data.topic_public, invite_requires_approval=data.invite_requires_approval)
    db.add(x); db.flush(); audit(db, user, "CLASS_CREATED", "class", str(x.id)); db.commit(); return class_json(x)


@router.post("/api/v1/classes/join")
def join_class(data: ClassJoinIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可以通过邀请码加入教学班")
    course = db.scalar(select(TeachingClass).where(TeachingClass.invite_code == data.invite_code.strip().upper()).with_for_update())
    if not course: raise ApiError(404, "INVITE_CODE_INVALID", "邀请码无效")
    if course.status != "ACTIVE": raise ApiError(409, "CLASS_ARCHIVED", "教学班已归档，无法加入")
    member = db.scalar(select(ClassMember).where(ClassMember.class_id == course.id, ClassMember.user_id == user.id).with_for_update())
    if member and member.status == "ACTIVE": raise ApiError(409, "CLASS_MEMBER_EXISTS", "你已加入该教学班")
    if course.invite_requires_approval:
        pending = db.scalar(select(ClassJoinRequest).where(ClassJoinRequest.class_id == course.id, ClassJoinRequest.user_id == user.id, ClassJoinRequest.status == "PENDING").with_for_update())
        if pending: raise ApiError(409, "CLASS_JOIN_PENDING", "加入申请正在等待教师审核")
        request = ClassJoinRequest(class_id=course.id, user_id=user.id); db.add(request); audit(db, user, "CLASS_JOIN_REQUESTED", "class", str(course.id)); db.commit()
        return {"status": "PENDING", "class_id": str(course.id), "class_name": course.name}
    if member: member.status = "ACTIVE"
    else: db.add(ClassMember(class_id=course.id, user_id=user.id))
    audit(db, user, "CLASS_JOINED_BY_INVITE", "class", str(course.id)); db.commit()
    return {"status": "APPROVED", "class_id": str(course.id), "class_name": course.name}


@router.get("/api/v1/classes/{cid}/join-requests")
def class_join_requests(cid: UUID, user: CurrentUser, db: Db):
    teacher(user); require_class(db, user, cid)
    rows = db.execute(select(ClassJoinRequest, User).join(User).where(ClassJoinRequest.class_id == cid).order_by(ClassJoinRequest.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "user_id": str(person.id), "student_no": person.login_name, "name": person.display_name, "status": item.status, "created_at": item.created_at} for item, person in rows]}


@router.post("/api/v1/classes/{cid}/join-requests/{rid}/decision")
def decide_class_join_request(cid: UUID, rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    request = db.scalar(select(ClassJoinRequest).where(ClassJoinRequest.id == rid, ClassJoinRequest.class_id == cid).with_for_update())
    if not request or request.status != "PENDING": raise ApiError(409, "CLASS_JOIN_NOT_PENDING", "该加入申请无法处理")
    request.status, request.resolved_at = decision, now()
    if decision == "APPROVED":
        member = db.scalar(select(ClassMember).where(ClassMember.class_id == cid, ClassMember.user_id == request.user_id).with_for_update())
        if member and member.status == "ACTIVE": raise ApiError(409, "CLASS_MEMBER_EXISTS", "该学生已加入教学班")
        if member: member.status = "ACTIVE"
        else: db.add(ClassMember(class_id=cid, user_id=request.user_id))
    audit(db, user, f"CLASS_JOIN_{decision}", "class_join_request", str(request.id)); db.commit()
    return {"id": str(request.id), "status": request.status}


@router.get("/api/v1/classes/current/context")
def context(user: CurrentUser, db: Db, class_id: UUID | None = Query(None)):
    course = user_class(db, user, class_id); m = membership(db, course.id, user.id) if course and user.role == "STUDENT" else None
    return {"user": {"id": str(user.id), "account": user.login_name, "name": user.display_name, "role": user.role}, "current_class": class_json(course) if course else None, "team_membership": None if not m else {"team_id": str(m[1].id), "team_name": m[1].name, "role": m[0].role}, "team_gate_required": bool(course and user.role == "STUDENT" and not m), "permissions": {"manage_class": user.role == "TEACHER", "access_coursework": user.role == "TEACHER" or bool(m)}}


@router.patch("/api/v1/classes/{cid}")
def update_class(cid: UUID, data: ClassUpdateIn, user: CsrfUser, db: Db):
    teacher(user)
    course = db.scalar(select(TeachingClass).where(TeachingClass.id == cid, TeachingClass.teacher_id == user.id).with_for_update())
    if not course: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可管理的教学班")
    if course.version != data.version: raise ApiError(409, "CLASS_VERSION_CONFLICT", "教学班已被修改，请刷新后重试", {"current_version": course.version})
    metadata_fields = {"semester", "name", "team_deadline", "topic_public", "invite_requires_approval"} & data.model_fields_set
    if course.status == "ARCHIVED" and metadata_fields: raise ApiError(409, "CLASS_ARCHIVED", "请先恢复教学班再编辑资料")
    changes = {}
    for field in ("semester", "name"):
        value = getattr(data, field)
        if value is not None:
            value = value.strip()
            if value != getattr(course, field): changes[field] = {"from": getattr(course, field), "to": value}; setattr(course, field, value)
    if "team_deadline" in data.model_fields_set and data.team_deadline != course.team_deadline:
        changes["team_deadline"] = {"from": course.team_deadline.isoformat() if course.team_deadline else None, "to": data.team_deadline.isoformat() if data.team_deadline else None}
        course.team_deadline = data.team_deadline
    for field in ("topic_public", "invite_requires_approval"):
        value = getattr(data, field)
        if value is not None and value != getattr(course, field):
            changes[field] = {"from": getattr(course, field), "to": value}; setattr(course, field, value)
    if data.status is not None and data.status != course.status:
        changes["status"] = {"from": course.status, "to": data.status}; course.status = data.status
    if changes:
        course.version += 1; audit(db, user, "CLASS_UPDATED", "class", str(cid), changes); db.commit()
    return class_json(course)


@router.delete("/api/v1/classes/{cid}", status_code=204)
def delete_class(cid: UUID, user: CsrfUser, db: Db):
    teacher(user)
    course = db.scalar(select(TeachingClass).where(TeachingClass.id == cid, TeachingClass.teacher_id == user.id).with_for_update())
    if not course: raise ApiError(404, "CLASS_NOT_FOUND", "未找到可管理的教学班")
    blockers = {
        "members": db.scalar(select(func.count()).select_from(ClassMember).where(ClassMember.class_id == cid)) or 0,
        "imports": db.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.class_id == cid)) or 0,
        "teams": db.scalar(select(func.count()).select_from(Team).where(Team.class_id == cid)) or 0,
        "assignments": db.scalar(select(func.count()).select_from(Assignment).where(Assignment.class_id == cid)) or 0,
    }
    if any(blockers.values()): raise ApiError(409, "CLASS_NOT_EMPTY", "教学班已有历史数据，请改用归档", blockers)
    audit(db, user, "CLASS_DELETED", "class", str(cid), {"semester": course.semester, "name": course.name})
    db.execute(delete(ClassJoinRequest).where(ClassJoinRequest.class_id == cid))
    db.delete(course); db.commit(); return Response(status_code=204)
