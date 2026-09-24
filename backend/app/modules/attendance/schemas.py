from __future__ import annotations

from pydantic import BaseModel, Field


class AttendanceSessionIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(default=15, ge=1, le=120)


class AttendanceCheckIn(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


class AttendanceCorrection(BaseModel):
    status: str = Field(pattern=r"^(PRESENT|LATE|ABSENT|LEAVE)$")
    note: str | None = Field(default=None, max_length=500)
