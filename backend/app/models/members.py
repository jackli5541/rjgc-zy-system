from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Index, Integer, Unicode as String, UnicodeText as Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from app.database import Base
from app.models._base import ForeignKey, uuid_pk

class TeachingClass(Base):
    __tablename__ = "teaching_classes"
    id: Mapped[UUID] = uuid_pk()
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course: Mapped[str] = mapped_column(String(80), default="软件工程")
    semester: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    invite_code: Mapped[str] = mapped_column(String(12), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    team_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_team_members: Mapped[int] = mapped_column(Integer, default=5)
    topic_public: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassMember(Base):
    __tablename__ = "class_members"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="STUDENT")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("class_id", "user_id", name="uq_class_member"),)


class ClassJoinRequest(Base):
    __tablename__ = "class_join_requests"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("uq_pending_class_join_request", ClassJoinRequest.class_id, ClassJoinRequest.user_id, unique=True, mssql_where=ClassJoinRequest.status == "PENDING")


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    leader_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    normalized_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    open_recruitment: Mapped[bool] = mapped_column(Boolean, default=True)
    max_members: Mapped[int] = mapped_column(Integer, default=5)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_team_name", Team.class_id, Team.normalized_name, unique=True, mssql_where=Team.status == "ACTIVE")


class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[UUID] = uuid_pk()
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_active_team_member", TeamMember.class_id, TeamMember.user_id, unique=True, mssql_where=TeamMember.status == "ACTIVE")


class TeamRequest(Base):
    __tablename__ = "team_requests"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    applicant_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    inviter_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="APPLICATION")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[UUID] = uuid_pk()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("teaching_classes.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    review_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("class_id", "normalized_name", name="uq_topic_name"),)
