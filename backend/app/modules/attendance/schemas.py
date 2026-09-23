from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field


class AttendanceScoreIn(BaseModel):
    score: Decimal | None = Field(None, ge=0, le=10)
