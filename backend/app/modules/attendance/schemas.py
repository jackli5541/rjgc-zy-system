from __future__ import annotations

from pydantic import BaseModel, Field


class AttendanceSessionIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(default=15, ge=1, le=120)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float = Field(ge=0, le=100, allow_inf_nan=False)
    radius_meters: int = Field(default=100, ge=30, le=500)


class AttendanceCheckIn(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float = Field(ge=0, le=100, allow_inf_nan=False)


class AttendanceCorrection(BaseModel):
    status: str = Field(pattern=r"^(PRESENT|LATE|ABSENT|LEAVE)$")
    note: str | None = Field(default=None, max_length=500)
