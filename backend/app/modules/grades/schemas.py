from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field


class CoefficientIn(BaseModel):
    coefficient: Decimal = Field(ge=0, decimal_places=2)
    version: int = Field(ge=1)


class GradePublishIn(BaseModel):
    reason: str = Field("", max_length=500)
