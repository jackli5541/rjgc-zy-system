from __future__ import annotations

from datetime import timedelta
from fastapi import APIRouter, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from typing import Literal
from uuid import UUID

from app.models import Assignment, ClassMember, Notification, Team, TeamMember, TeamRequest, Topic, User
from app.core.audit import audit, notify
from app.core.deps import CsrfUser, CurrentUser, Db, membership, require_class, require_team_window, require_writable_class, teacher, user_class
from app.core.errors import ApiError
from app.core.files import enqueue_archive_export
from app.core.schemas import ReasonIn
from app.core.utils import now
from app.modules.members.schemas import AutoGroupIn, InviteIn, TeamIn, TopicIn, TransferIn
from app.modules.members.service import set_team_recruitment, team_json, team_payload

router = APIRouter()

@router.get("/api/v1/teams")
def teams(user: CurrentUser, db: Db, class_id: UUID = Query()):
    course = require_class(db, user, class_id)
    query = select(Team).where(Team.class_id == class_id, Team.status == "ACTIVE")
    own_team = None
    if user.role == "STUDENT":
        own_team = membership(db, class_id, user.id)
        if own_team:
            query = query.where(Team.id == own_team[1].id)
    items = db.scalars(query.order_by(Team.created_at)).all()
    if not items:
        return {"items": [], "total": 0}
    team_ids = [item.id for item in items]
    leaders = {item.id: item.display_name for item in db.scalars(select(User).where(User.id.in_({team.leader_id for team in items}))).all()}
    member_counts = dict(db.execute(
        select(TeamMember.team_id, func.count())
        .where(TeamMember.team_id.in_(team_ids), TeamMember.status == "ACTIVE")
        .group_by(TeamMember.team_id)
    ).all())
    topics = {item.team_id: item for item in db.scalars(select(Topic).where(Topic.team_id.in_(team_ids))).all()}
    pending_counts = dict(db.execute(
        select(TeamRequest.team_id, func.count())
        .where(TeamRequest.team_id.in_(team_ids), TeamRequest.status == "PENDING")
        .group_by(TeamRequest.team_id)
    ).all())
    own_team_id = own_team[1].id if own_team else None
    payloads = [
        team_payload(item, user, leaders[item.leader_id], member_counts.get(item.id, 0), topics.get(item.id), pending_counts.get(item.id, 0), course.topic_public, own_team_id)
        for item in items
    ]
    return {"items": payloads, "total": len(payloads)}


@router.post("/api/v1/teams", status_code=201)
def create_team(data: TeamIn, user: CsrfUser, db: Db):
    if user.role != "STUDENT": raise ApiError(403, "STUDENT_REQUIRED", "仅学生可创建小组")
    course = require_writable_class(db, user, data.class_id); require_team_window(course, user)
    if membership(db, course.id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
    x = Team(class_id=course.id, leader_id=user.id, name=data.name.strip(), normalized_name="".join(data.name.casefold().split()), open_recruitment=data.open_recruitment); db.add(x)
    try:
        db.flush(); db.add(TeamMember(team_id=x.id, class_id=course.id, user_id=user.id, role="LEADER")); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == course.id, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); notify(db, user.id, "TOPIC_REQUIRED", "小组已创建，请提交选题", "team", str(x.id)); audit(db, user, "TEAM_CREATED", "team", str(x.id)); db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "TEAM_NAME_EXISTS", "小组名称已被使用")
    return team_json(db, x, user)


@router.post("/api/v1/classes/{cid}/teams/auto-group", status_code=201)
def auto_group_teams(cid: UUID, data: AutoGroupIn, user: CsrfUser, db: Db):
    teacher(user); require_writable_class(db, user, cid)
    grouped_user_ids = select(TeamMember.user_id).join(Team).where(TeamMember.class_id == cid, TeamMember.status == "ACTIVE", Team.status == "ACTIVE")
    students = db.scalars(select(User).join(ClassMember).where(ClassMember.class_id == cid, ClassMember.status == "ACTIVE", User.id.not_in(grouped_user_ids)).order_by(User.login_name, User.id)).all()
    if not students: return {"created": 0, "assigned": 0, "teams": []}
    existing_names = set(db.scalars(select(Team.normalized_name).where(Team.class_id == cid)).all())
    created = []
    next_number = 1
    for offset in range(0, len(students), data.group_size):
        members = students[offset:offset + data.group_size]
        while f"小组{next_number}" in existing_names: next_number += 1
        name = f"小组{next_number}"
        existing_names.add(name); next_number += 1
        team = Team(class_id=cid, leader_id=members[0].id, name=name, normalized_name=name, open_recruitment=False, max_members=data.group_size)
        db.add(team); db.flush()
        for index, student in enumerate(members):
            db.add(TeamMember(team_id=team.id, class_id=cid, user_id=student.id, role="LEADER" if index == 0 else "MEMBER"))
            notify(db, student.id, "TEAM_ASSIGNED", f"教师已将你分入「{name}」", "team", str(team.id))
        created.append({"id": str(team.id), "name": name, "member_count": len(members)})
    db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == cid, TeamRequest.applicant_id.in_([student.id for student in students]), TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now()))
    audit(db, user, "TEAMS_AUTO_GROUPED", "class", str(cid), {"group_size": data.group_size, "assigned": len(students), "created": len(created)})
    db.commit()
    return {"created": len(created), "assigned": len(students), "teams": created}


@router.get("/api/v1/teams/{tid}")
def team_detail(tid: UUID, user: CurrentUser, db: Db):
    x = db.get(Team, tid)
    if not x: raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    require_class(db, user, x.class_id); out = team_json(db, x, user)
    own_team = membership(db, x.class_id, user.id) if user.role == "STUDENT" else None
    if own_team and own_team[1].id != x.id:
        raise ApiError(403, "TEAM_ACCESS_DENIED", "只能查看本组信息")
    if user.role == "TEACHER" or own_team:
        rows = db.execute(select(TeamMember, User).join(User).where(TeamMember.team_id == tid, TeamMember.status == "ACTIVE")).all(); out["members"] = [{"id": str(p.id), "name": p.display_name, "student_no": p.login_name, "role": m.role} for m, p in rows]
    return out


@router.post("/api/v1/teams/{tid}/applications", status_code=201)
def apply_team(tid: UUID, user: CsrfUser, db: Db):
    x = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not x or not x.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组暂不接受申请")
    course = require_writable_class(db, user, x.class_id); require_team_window(course, user)
    if membership(db, x.class_id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
    if db.scalar(select(TeamRequest).where(TeamRequest.team_id == tid, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING")): raise ApiError(409, "APPLICATION_EXISTS", "已提交过申请")
    req = TeamRequest(class_id=x.class_id, team_id=tid, applicant_id=user.id); db.add(req); notify(db, x.leader_id, "TEAM_APPLICATION", f"{user.display_name} 申请加入小组"); db.commit(); return {"id": str(req.id), "status": req.status}


@router.post("/api/v1/teams/{tid}/close-recruitment")
def close_team_recruitment(tid: UUID, user: CsrfUser, db: Db):
    return set_team_recruitment(tid, False, user, db)


@router.post("/api/v1/teams/{tid}/open-recruitment")
def open_team_recruitment(tid: UUID, user: CsrfUser, db: Db):
    return set_team_recruitment(tid, True, user, db)


@router.get("/api/v1/team-requests")
def requests(user: CurrentUser, db: Db, class_id: UUID = Query()):
    require_class(db, user, class_id); q = select(TeamRequest, Team, User).join(Team, Team.id == TeamRequest.team_id).join(User, User.id == TeamRequest.applicant_id).where(TeamRequest.class_id == class_id)
    if user.role == "STUDENT": q = q.where(or_(TeamRequest.applicant_id == user.id, Team.leader_id == user.id))
    rows = db.execute(q.order_by(TeamRequest.created_at.desc())).all()
    items = [{"id": str(r.id), "team_id": str(t.id), "team_name": t.name, "applicant_id": str(p.id), "applicant_name": p.display_name, "kind": r.kind, "status": r.status, "is_incoming": t.leader_id == user.id, "created_at": r.created_at} for r, t, p in rows]
    if user.role == "STUDENT":
        memberships = db.execute(select(TeamMember, Team).join(Team, Team.id == TeamMember.team_id).where(TeamMember.class_id == class_id, TeamMember.user_id == user.id, TeamMember.status == "LEFT")).all()
        items.extend({"id": str(member.id), "team_id": str(team.id), "team_name": team.name, "applicant_id": str(user.id), "applicant_name": user.display_name, "kind": "MEMBERSHIP", "status": member.status, "is_incoming": False, "created_at": member.joined_at} for member, team in memberships)
        items.sort(key=lambda item: item["created_at"].timestamp() if item["created_at"] else 0, reverse=True)
    return {"items": items}


@router.post("/api/v1/team-requests/{rid}/decision")
def request_decision(rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    req = db.scalar(select(TeamRequest).where(TeamRequest.id == rid).with_for_update()); x = db.scalar(select(Team).where(Team.id == req.team_id).with_for_update()) if req else None
    if not req or req.status != "PENDING": raise ApiError(409, "REQUEST_NOT_PENDING", "申请已处理")
    if not x or x.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可处理申请")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    if decision == "APPROVED":
        if x.status != "ACTIVE" or not x.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组已截止招募，不能加入")
        if membership(db, req.class_id, req.applicant_id): raise ApiError(409, "ALREADY_IN_TEAM", "申请人已加入其他小组")
        db.add(TeamMember(team_id=x.id, class_id=req.class_id, user_id=req.applicant_id)); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == req.class_id, TeamRequest.applicant_id == req.applicant_id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); req.status = "APPROVED"; notify(db, req.applicant_id, "TEAM_JOINED", f"已加入小组「{x.name}」")
    else: req.status, req.resolved_at = "REJECTED", now(); notify(db, req.applicant_id, "TEAM_REJECTED", f"加入「{x.name}」的申请未通过")
    audit(db, user, "TEAM_REQUEST_DECIDED", "team_request", str(req.id), {"decision": decision}); db.commit(); return {"id": str(req.id), "status": req.status}


@router.delete("/api/v1/team-requests/{rid}", status_code=204)
def cancel_request(rid: UUID, user: CsrfUser, db: Db):
    req = db.get(TeamRequest, rid)
    can_cancel = req and (req.applicant_id == user.id or (req.kind == "INVITATION" and req.inviter_id == user.id))
    if not can_cancel or req.status != "PENDING": raise ApiError(409, "REQUEST_NOT_CANCELLABLE", "申请或邀请无法取消")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    req.status, req.resolved_at = "CANCELLED", now(); audit(db, user, "TEAM_REQUEST_CANCELLED", "team_request", str(req.id)); db.commit(); return Response(status_code=204)


@router.post("/api/v1/teams/{tid}/topic")
def topic(tid: UUID, data: TopicIn, user: CsrfUser, db: Db):
    x = db.get(Team, tid)
    if not x or x.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可提交选题")
    require_writable_class(db, user, x.class_id)
    norm = "".join(data.name.casefold().split()); item = db.scalar(select(Topic).where(Topic.team_id == tid))
    if item: item.name, item.normalized_name, item.description, item.review_status, item.version = data.name.strip(), norm, data.description, "PENDING", item.version + 1
    else: item = Topic(class_id=x.class_id, team_id=tid, name=data.name.strip(), normalized_name=norm, description=data.description); db.add(item)
    try:
        db.flush()
        db.execute(Notification.__table__.delete().where(Notification.user_id == user.id, Notification.kind == "TOPIC_REQUIRED", Notification.object_type == "team", Notification.object_id == str(tid)))
        audit(db, user, "TOPIC_SUBMITTED", "team", str(tid)); db.commit()
    except IntegrityError: db.rollback(); raise ApiError(409, "TOPIC_DUPLICATE", "该选题已被使用，请重新填写")
    return {"id": str(item.id), "name": item.name, "status": item.review_status}


@router.post("/api/v1/teams/{tid}/invitations", status_code=201)
def invite_member(tid: UUID, data: InviteIn, user: CsrfUser, db: Db):
    team = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not team or team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可邀请成员")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    if team.status != "ACTIVE" or not team.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组已截止招募，不能邀请成员")
    target = db.get(User, data.student_id)
    if not target or not db.scalar(select(ClassMember).where(ClassMember.class_id == team.class_id, ClassMember.user_id == target.id, ClassMember.status == "ACTIVE")): raise ApiError(404, "MEMBER_NOT_FOUND", "学生不在当前教学班")
    if membership(db, team.class_id, target.id): raise ApiError(409, "ALREADY_IN_TEAM", "该学生已经加入小组")
    exists = db.scalar(select(TeamRequest).where(TeamRequest.team_id == tid, TeamRequest.applicant_id == target.id, TeamRequest.kind == "INVITATION", TeamRequest.status == "PENDING"))
    if exists: raise ApiError(409, "INVITATION_EXISTS", "已邀请该学生")
    req = TeamRequest(class_id=team.class_id, team_id=tid, applicant_id=target.id, inviter_id=user.id, kind="INVITATION", expires_at=now() + timedelta(days=7)); db.add(req); notify(db, target.id, "TEAM_INVITATION", f"邀请你加入「{team.name}」"); db.commit(); return {"id": str(req.id), "status": req.status}


@router.post("/api/v1/team-requests/{rid}/respond")
def respond_invitation(rid: UUID, decision: Literal["APPROVED", "REJECTED"], user: CsrfUser, db: Db):
    req = db.scalar(select(TeamRequest).where(TeamRequest.id == rid).with_for_update()); team = db.scalar(select(Team).where(Team.id == req.team_id).with_for_update()) if req else None
    if not req or req.kind != "INVITATION" or req.applicant_id != user.id or req.status != "PENDING": raise ApiError(409, "INVITATION_NOT_PENDING", "邀请已处理")
    course = require_writable_class(db, user, req.class_id); require_team_window(course, user)
    if req.expires_at and req.expires_at < now(): req.status = "EXPIRED"; db.commit(); raise ApiError(409, "INVITATION_EXPIRED", "邀请已过期")
    if decision == "APPROVED":
        if not team or team.status != "ACTIVE" or not team.open_recruitment: raise ApiError(409, "TEAM_NOT_OPEN", "该小组已截止招募，不能加入")
        if membership(db, req.class_id, user.id): raise ApiError(409, "ALREADY_IN_TEAM", "你已经加入小组")
        db.add(TeamMember(team_id=team.id, class_id=req.class_id, user_id=user.id)); db.execute(TeamRequest.__table__.update().where(TeamRequest.class_id == req.class_id, TeamRequest.applicant_id == user.id, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); req.status = "APPROVED"
    else: req.status = "REJECTED"
    req.resolved_at = now(); audit(db, user, "TEAM_INVITATION_RESPONDED", "team_request", str(req.id), {"decision": decision}); db.commit(); return {"id": str(req.id), "status": req.status}


@router.post("/api/v1/teams/{tid}/transfer")
def transfer_leader(tid: UUID, data: TransferIn, user: CsrfUser, db: Db):
    team = db.get(Team, tid)
    if not team or team.leader_id != user.id: raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长可移交")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    old = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == user.id, TeamMember.status == "ACTIVE")); new = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == data.new_leader_id, TeamMember.status == "ACTIVE"))
    if not new: raise ApiError(422, "NEW_LEADER_INVALID", "新组长必须是当前组员")
    team.leader_id, old.role, new.role, team.version = data.new_leader_id, "MEMBER", "LEADER", team.version + 1; audit(db, user, "TEAM_LEADER_TRANSFERRED", "team", str(tid)); db.commit(); return team_json(db, team, user)


@router.post("/api/v1/teams/{tid}/leave", status_code=204)
def leave_team(tid: UUID, user: CsrfUser, db: Db):
    team = db.get(Team, tid); member = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == user.id, TeamMember.status == "ACTIVE"))
    if not team or not member: raise ApiError(404, "TEAM_MEMBERSHIP_NOT_FOUND", "不在该小组")
    course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    if team.leader_id == user.id: raise ApiError(409, "LEADER_TRANSFER_REQUIRED", "组长退出前必须移交组长")
    member.status = "LEFT"; audit(db, user, "TEAM_LEFT", "team", str(tid)); db.commit(); return Response(status_code=204)


@router.delete("/api/v1/teams/{tid}", status_code=204)
def disband_team(tid: UUID, user: CsrfUser, db: Db):
    team = db.scalar(select(Team).where(Team.id == tid, Team.status == "ACTIVE").with_for_update())
    if not team: raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    if user.role == "TEACHER":
        require_writable_class(db, user, team.class_id)
    elif team.leader_id == user.id:
        course = require_writable_class(db, user, team.class_id); require_team_window(course, user)
    else:
        raise ApiError(403, "TEAM_LEADER_REQUIRED", "仅组长或任课教师可解散小组")
    team.status = "DISBANDED"; db.execute(TeamMember.__table__.update().where(TeamMember.team_id == tid, TeamMember.status == "ACTIVE").values(status="LEFT")); db.execute(TeamRequest.__table__.update().where(TeamRequest.team_id == tid, TeamRequest.status == "PENDING").values(status="INVALID", resolved_at=now())); audit(db, user, "TEAM_DISBANDED", "team", str(tid)); db.commit(); return Response(status_code=204)


@router.delete("/api/v1/teams/{tid}/members/{uid}", status_code=204)
def teacher_remove_team_member(tid: UUID, uid: UUID, user: CsrfUser, db: Db):
    teacher(user); team = db.scalar(select(Team).where(Team.id == tid).with_for_update())
    if not team or not user_class(db, user, team.class_id): raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    require_writable_class(db, user, team.class_id)
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id == uid, TeamMember.status == "ACTIVE").with_for_update())
    if not member: raise ApiError(404, "TEAM_MEMBERSHIP_NOT_FOUND", "该学生不在小组中")
    member.status = "REMOVED"
    if team.leader_id == uid:
        replacement = db.scalar(select(TeamMember).where(TeamMember.team_id == tid, TeamMember.user_id != uid, TeamMember.status == "ACTIVE").order_by(TeamMember.joined_at).limit(1))
        if replacement:
            replacement.role = "LEADER"; team.leader_id = replacement.user_id
        else:
            team.status = "DISBANDED"
    team.version += 1; notify(db, uid, "TEAM_MEMBER_REMOVED", f"教师已将你移出小组「{team.name}」")
    audit(db, user, "TEAM_MEMBER_REMOVED", "team", str(tid), {"user_id": str(uid)}); db.commit(); return Response(status_code=204)


@router.post("/api/v1/topics/{topic_id}/decision")
def topic_decision(topic_id: UUID, decision: Literal["APPROVED", "REJECTED"], data: ReasonIn, user: CsrfUser, db: Db):
    teacher(user); topic = db.get(Topic, topic_id)
    if not topic or not user_class(db, user, topic.class_id): raise ApiError(404, "TOPIC_NOT_FOUND", "选题不存在")
    require_writable_class(db, user, topic.class_id)
    reason = (data.reason or "").strip()
    if decision == "REJECTED" and not reason: raise ApiError(422, "TOPIC_REASON_REQUIRED", "驳回选题时必须填写原因")
    if decision == "APPROVED" and not reason: reason = "审核通过"
    topic.review_status, topic.review_reason = decision, reason
    decision_label = "已通过" if decision == "APPROVED" else "已驳回"
    for member in db.scalars(select(TeamMember).where(TeamMember.team_id == topic.team_id, TeamMember.status == "ACTIVE")): notify(db, member.user_id, "TOPIC_DECISION", f"选题审核结果：{decision_label}")
    audit(db, user, "TOPIC_DECIDED", "topic", str(topic.id), {"decision": decision, "reason": reason}); db.commit(); return {"id": str(topic.id), "status": topic.review_status, "reason": topic.review_reason}


@router.post("/api/v1/teams/{tid}/coursework.zip", status_code=202)
def queue_team_coursework(tid: UUID, user: CsrfUser, db: Db):
    teacher(user)
    team_item = db.get(Team, tid)
    if not team_item or team_item.status != "ACTIVE" or not user_class(db, user, team_item.class_id):
        raise ApiError(404, "TEAM_NOT_FOUND", "小组不存在")
    has_assignments = db.scalar(select(Assignment.id).where(Assignment.class_id == team_item.class_id, Assignment.submitter_type == "TEAM", Assignment.status.in_(["PUBLISHED", "CLOSED"])).limit(1))
    if not has_assignments:
        raise ApiError(409, "NO_COURSEWORK_TO_EXPORT", "暂无作业可导出")
    return enqueue_archive_export(db, user, "TEAM", {"team_id": str(tid)}, "team-coursework.zip")
