from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AgentScope = Literal["assignment:read", "submission:read"]


class AgentTokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[AgentScope] = Field(default_factory=lambda: ["assignment:read", "submission:read"], min_length=1)
    class_ids: list[UUID] = Field(default_factory=list, max_length=100)
    assignment_ids: list[UUID] = Field(default_factory=list, max_length=500)
    expose_real_name: bool = True
    expires_days: int = Field(90, ge=1, le=365)


class AgentTokenUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[AgentScope] = Field(min_length=1)
    class_ids: list[UUID] = Field(default_factory=list, max_length=100)
    assignment_ids: list[UUID] = Field(default_factory=list, max_length=500)
    expose_real_name: bool = True
    # 传入则从现在起重新计算有效期（续期）
    expires_days: int | None = Field(None, ge=1, le=365)
