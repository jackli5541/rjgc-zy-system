from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class LoginIn(BaseModel):
    account: str; password: str; role: Literal["teacher", "student"] | None = None


class PasswordIn(BaseModel): current_password: str; new_password: str = Field(min_length=8, max_length=128)


class MenuPermissionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: dict[Literal["TEACHER", "STUDENT"], list[str]]
