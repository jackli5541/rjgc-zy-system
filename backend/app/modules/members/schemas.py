from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID


class ClassIn(BaseModel):
    semester: str = Field(min_length=2, max_length=40); name: str = Field(min_length=2, max_length=100); team_deadline: datetime | None = None; topic_public: bool = False; invite_requires_approval: bool = True


class TeamIn(BaseModel):
    class_id: UUID; name: str = Field(min_length=2, max_length=40); open_recruitment: bool = True


class AutoGroupIn(BaseModel):
    group_size: int = Field(default=6, ge=2, le=20)


class TopicIn(BaseModel):
    name: str = Field(min_length=2, max_length=100); description: str = Field("", max_length=1000)


class ClassJoinIn(BaseModel): invite_code: str = Field(min_length=4, max_length=12)


class InviteIn(BaseModel): student_id: UUID


class TransferIn(BaseModel): new_leader_id: UUID


class ClassUpdateIn(BaseModel):
    version: int = Field(ge=1)
    semester: str | None = Field(None, min_length=2, max_length=40)
    name: str | None = Field(None, min_length=2, max_length=100)
    team_deadline: datetime | None = None
    topic_public: bool | None = None
    invite_requires_approval: bool | None = None
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class MemberCreateIn(BaseModel):
    student_no: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)


class MemberUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
