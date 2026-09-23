from __future__ import annotations

from pydantic import BaseModel, Field


class ReasonIn(BaseModel): reason: str = Field(min_length=2, max_length=500)
