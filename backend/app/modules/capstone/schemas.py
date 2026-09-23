from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.settings import settings

class CapstoneDocumentCreateIn(BaseModel):
    stage: Literal["PROPOSAL", "REQUIREMENTS", "DESIGN", "IMPLEMENTATION", "TESTING"]
    name: str = Field(min_length=1, max_length=120)


class CapstoneDocumentRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CapstoneDocumentUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    markdown_content: str = Field(max_length=settings.markdown_max_bytes)


class CapstoneConfigIn(BaseModel):
    due_at: datetime | None = None


class CapstoneGradeIn(BaseModel):
    score: Decimal | None = Field(None, ge=0, le=100)
    comment: str = Field("", max_length=2000)


class CapstoneModuleIn(BaseModel):
    module_name: str = Field("", max_length=120)
