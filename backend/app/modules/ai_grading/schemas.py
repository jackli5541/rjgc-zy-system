from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AiGradingJobIn(BaseModel):
    submission_version_ids: list[UUID] = Field(min_length=1, max_length=100)


class AiGradingAcceptIn(BaseModel):
    grade: Literal["A", "B", "C", "D", "E"]
    comment: str = Field("", max_length=20000)
