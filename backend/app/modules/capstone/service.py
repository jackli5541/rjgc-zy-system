from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import Session
from uuid import UUID

from app.models import CAPSTONE_STAGES, CapstoneAsset, CapstoneConfig, CapstoneDocument, CapstoneUnlock, ClassMember, TeamMember, User
from app.core.deps import membership, require_class
from app.core.errors import ApiError
from app.core.utils import now

CAPSTONE_STAGE_INFO = {
    "PROPOSAL": {"folder": "立项", "doc_name": "立项书.md", "fallback_content": "# 立项书\n\n"},
    "REQUIREMENTS": {"folder": "需求", "doc_name": "需求规格说明.md", "fallback_content": "# 需求规格说明\n\n"},
    "DESIGN": {"folder": "设计", "doc_name": "软件设计文档.md", "fallback_content": "# 软件设计文档\n\n"},
    "IMPLEMENTATION": {"folder": "编码与实现", "doc_name": "软件实现文档.md", "fallback_content": "# 软件实现文档\n\n"},
    "TESTING": {"folder": "测试", "doc_name": "测试文档.md", "fallback_content": "# 测试文档\n\n"},
}


CAPSTONE_STAGE_ORDER = case({stage: index for index, stage in enumerate(CAPSTONE_STAGES)}, value=CapstoneDocument.stage, else_=len(CAPSTONE_STAGES))


def capstone_locked(db: Session, class_id: UUID, student_user_id: UUID) -> bool:
    config = db.get(CapstoneConfig, class_id)
    if not config or not config.due_at or config.due_at > now():
        return False
    return db.get(CapstoneUnlock, (class_id, student_user_id)) is None


def capstone_document_json(item: CapstoneDocument, editor_name: str = "") -> dict:
    return {"id": str(item.id), "stage": item.stage, "name": item.name, "sort_order": item.sort_order, "revision": item.revision, "updated_at": item.updated_at.isoformat() if item.updated_at else None, "updated_by": editor_name, "locked": False}


def capstone_document_content_json(item: CapstoneDocument, editor_name: str = "") -> dict:
    result = capstone_document_json(item, editor_name)
    result["markdown_content"] = item.markdown_content
    return result


def capstone_workspace_json(db: Session, class_id: UUID, student_user_id: UUID) -> dict:
    rows = db.execute(
        select(CapstoneDocument, User.display_name)
        .outerjoin(User, User.id == CapstoneDocument.updated_by)
        .where(CapstoneDocument.class_id == class_id, CapstoneDocument.student_user_id == student_user_id, CapstoneDocument.active == True)  # noqa: E712
        .order_by(CAPSTONE_STAGE_ORDER, CapstoneDocument.sort_order, CapstoneDocument.created_at)
    ).all()
    config = db.get(CapstoneConfig, class_id)
    return {
        "id": f"{class_id}:{student_user_id}",
        "documents": [capstone_document_json(item, editor_name or "") for item, editor_name in rows],
        "due_at": config.due_at.isoformat() if config and config.due_at else None,
        "locked": capstone_locked(db, class_id, student_user_id),
        "unlocked": db.get(CapstoneUnlock, (class_id, student_user_id)) is not None,
    }


def require_capstone_target_student(db: Session, class_id: UUID, user: User, student_id: UUID | None) -> UUID:
    if user.role == "TEACHER":
        if not student_id:
            raise ApiError(422, "STUDENT_ID_REQUIRED", "请指定要查看的学生")
        if not db.scalar(select(ClassMember.id).where(ClassMember.class_id == class_id, ClassMember.user_id == student_id, ClassMember.status == "ACTIVE", ClassMember.role == "STUDENT")):
            raise ApiError(404, "STUDENT_NOT_FOUND", "该学生不在本班")
        return student_id
    return user.id


def capstone_teammate_ids(db: Session, class_id: UUID, user_id: UUID) -> set[UUID]:
    row = membership(db, class_id, user_id)
    if not row:
        return set()
    return set(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == row[1].id, TeamMember.status == "ACTIVE")).all())


def capstone_module_writer(db: Session, class_id: UUID, user: User, student_id: UUID) -> bool:
    if user.role == "TEACHER":
        return True
    if user.role != "STUDENT":
        return False
    row = membership(db, class_id, user.id)
    if not row or row[0].role != "LEADER":
        return False
    return db.scalar(select(TeamMember.id).where(TeamMember.team_id == row[1].id, TeamMember.user_id == student_id, TeamMember.status == "ACTIVE").limit(1)) is not None


def require_capstone_document(db: Session, class_id: UUID, document_id: UUID, user: User, *, for_write: bool = False) -> CapstoneDocument:
    document = db.get(CapstoneDocument, document_id)
    if not document or not document.active or document.class_id != class_id:
        raise ApiError(404, "CAPSTONE_DOCUMENT_NOT_FOUND", "文档不存在")
    require_class(db, user, class_id)
    if user.role == "STUDENT" and document.student_user_id != user.id:
        if for_write or document.student_user_id not in capstone_teammate_ids(db, class_id, user.id):
            raise ApiError(404, "CAPSTONE_DOCUMENT_NOT_FOUND", "文档不存在")
    return document


def require_capstone_asset_access(db: Session, user: User, asset_id: UUID) -> CapstoneAsset:
    asset = db.get(CapstoneAsset, asset_id)
    if not asset:
        raise ApiError(404, "CAPSTONE_ASSET_NOT_FOUND", "图片不存在")
    document = db.get(CapstoneDocument, asset.document_id)
    if not document:
        raise ApiError(404, "CAPSTONE_ASSET_NOT_FOUND", "图片不存在")
    require_class(db, user, document.class_id)
    if user.role == "STUDENT" and document.student_user_id != user.id:
        raise ApiError(404, "CAPSTONE_ASSET_NOT_FOUND", "图片不存在")
    return asset
