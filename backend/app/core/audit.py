from __future__ import annotations

from sqlalchemy.orm import Session
from uuid import UUID

from app.models import Assignment, AuditLog, ClassJoinRequest, Notification, PeerReview, ReviewCampaign, Submission, SubmissionAssessment, TeachingClass, Team, TeamRequest, Topic, User
from app.realtime import publish_event
from app.core.context import request_client_id, request_ip_address, request_trace_id

def realtime_scopes(action: str) -> list[str]:
    if action.startswith(("CLASS_", "ROSTER_")): return ["classes", "members", "dashboard", "audit"]
    if action.startswith("TEAM_") or action.startswith("TOPIC_") or action == "TEAMS_AUTO_GROUPED": return ["teams", "members", "dashboard", "audit"]
    if action.startswith("ASSIGNMENT_"): return ["assignments", "dashboard", "audit"]
    if action.startswith("SUBMISSION_"): return ["submissions", "assignments", "dashboard", "grades", "audit"]
    if action.startswith(("PEER_", "REVIEW_")): return ["reviews", "submissions", "grades", "dashboard", "audit"]
    if action.startswith(("TEACHER_", "GRADE_", "GRADES_")): return ["submissions", "grades", "dashboard", "audit"]
    return ["audit"]


def realtime_class_id(db: Session, kind: str, oid: str, changes: dict) -> UUID | None:
    try:
        object_id = UUID(str(oid))
    except (TypeError, ValueError):
        return None
    if kind == "class": return object_id
    if changes.get("class_id"):
        try: return UUID(str(changes["class_id"]))
        except (TypeError, ValueError): pass
    if kind == "assignment":
        item = db.get(Assignment, object_id); return item.class_id if item else None
    if kind == "team":
        item = db.get(Team, object_id); return item.class_id if item else None
    if kind == "topic":
        item = db.get(Topic, object_id); return item.class_id if item else None
    if kind == "submission":
        item = db.get(Submission, object_id); assignment = db.get(Assignment, item.assignment_id) if item else None; return assignment.class_id if assignment else None
    if kind == "submission_assessment":
        item = db.get(SubmissionAssessment, object_id); assignment = db.get(Assignment, item.assignment_id) if item else None; return assignment.class_id if assignment else None
    if kind in {"review_campaign", "peer_review"}:
        campaign = db.get(ReviewCampaign, object_id) if kind == "review_campaign" else None
        if kind == "peer_review":
            review = db.get(PeerReview, object_id); campaign = db.get(ReviewCampaign, review.campaign_id) if review else None
        return campaign.class_id if campaign else None
    if kind in {"team_request", "class_join_request"}:
        model = TeamRequest if kind == "team_request" else ClassJoinRequest
        item = db.get(model, object_id); return item.class_id if item else None
    return None


def audit(db: Session, user: User | None, action: str, kind: str, oid: str, changes: dict | None = None):
    class_id = realtime_class_id(db, kind, oid, changes or {})
    course = db.get(TeachingClass, class_id) if class_id else None
    db.add(AuditLog(actor_id=user.id if user else None, class_id=class_id, class_semester=course.semester if course else None, class_name=course.name if course else None, action=action, object_type=kind, object_id=oid, changes=changes or {}, request_id=request_trace_id.get(), ip_address=request_ip_address.get()))
    if class_id:
        publish_event(db, class_id=class_id, scopes=realtime_scopes(action), resource_type=kind, resource_id=oid, source_client_id=request_client_id.get())
    elif user:
        publish_event(db, user_id=user.id, scopes=["audit"], resource_type=kind, resource_id=oid, source_client_id=request_client_id.get())


def notify(db: Session, uid: UUID, kind: str, title: str, object_type: str | None = None, object_id: str | None = None):
    db.add(Notification(user_id=uid, kind=kind, title=title, object_type=object_type, object_id=object_id))
    scopes = ["notifications"]
    if kind.startswith("TEAM_") or kind == "TOPIC_REQUIRED": scopes.extend(["teams", "members", "dashboard"])
    if kind.startswith("REVIEW_"): scopes.extend(["reviews", "dashboard"])
    if kind.startswith("GRADE_"): scopes.extend(["grades", "dashboard"])
    publish_event(db, user_id=uid, scopes=scopes, resource_type=object_type or "notification", resource_id=object_id, source_client_id=request_client_id.get())
