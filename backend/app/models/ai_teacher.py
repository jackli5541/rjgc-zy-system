from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, JSON, Unicode as String, UnicodeText as Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.utils import now
from app.models._base import ForeignKey, uuid_pk


class AiKnowledgeChunk(Base):
    __tablename__ = "ai_teacher_knowledge_chunks"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    owner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str | None] = mapped_column(String(80))
    source_title: Mapped[str] = mapped_column(String(255))
    visibility: Mapped[str] = mapped_column(String(32))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[str | None] = mapped_column(Text)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), onupdate=now)


Index("ix_ai_chunks_assignment_visibility", AiKnowledgeChunk.assignment_id, AiKnowledgeChunk.visibility)
Index("ix_ai_chunks_assignment_owner", AiKnowledgeChunk.assignment_id, AiKnowledgeChunk.owner_user_id, AiKnowledgeChunk.owner_team_id)


class AiChatMessage(Base):
    __tablename__ = "ai_teacher_chat_messages"
    id: Mapped[UUID] = uuid_pk()
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    contexts: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now(), index=True)


Index("ix_ai_chat_assignment_student_created", AiChatMessage.assignment_id, AiChatMessage.student_id, AiChatMessage.created_at)


class AiSubjectKnowledge(Base):
    __tablename__ = "ai_teacher_subject_knowledge"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())


class AiKnowledgeNode(Base):
    __tablename__ = "ai_teacher_knowledge_nodes"
    id: Mapped[UUID] = uuid_pk()
    subject: Mapped[str] = mapped_column(String(80))
    key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(32))
    extra_metadata: Mapped[str] = mapped_column("metadata", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=func.now())
