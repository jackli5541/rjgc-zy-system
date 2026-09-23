from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID


class TeachingMaterialFolderIn(BaseModel):
    class_id: UUID
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)


class TeachingMaterialRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeachingMaterialMoveIn(BaseModel):
    direction: Literal["up", "down"]
