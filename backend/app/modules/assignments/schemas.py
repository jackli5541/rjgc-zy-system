from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from uuid import UUID

from app.settings import settings

class AssignmentFields(BaseModel):
    title: str = Field(min_length=2, max_length=100); description: str = Field(min_length=1, max_length=5000); submitter_type: Literal["TEAM", "INDIVIDUAL"]; kind: Literal["ASSIGNMENT", "EXPERIMENT"] = "ASSIGNMENT"; starts_at: datetime | None = None; due_at: datetime; allow_late: bool = False; publish: bool = True
    auto_review_enabled: bool = False
    auto_review_mode: Literal["TEAM"] | None = None
    auto_review_criteria_text: str = Field("", max_length=5000)
    auto_review_due_at: datetime | None = None


class AssignmentIn(AssignmentFields):
    class_id: UUID


class AssignmentBulkIn(AssignmentFields):
    class_ids: list[UUID] = Field(min_length=1)


class AllocatedCampaignIn(BaseModel):
    assignment_id: UUID
    mode: Literal["TEAM"]
    criteria_text: str = Field("", max_length=5000)
    criteria_file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    due_at: datetime


class ReviewIn(BaseModel):
    score: float | None = Field(None, ge=0, le=100)
    comment: str = Field(max_length=2000)
    reviewee_id: UUID | None = None
    scores: dict[str, float] | None = None


class SubmissionAssessmentIn(BaseModel):
    grade: Literal["A", "B", "C", "D", "E"]
    comment: str = Field("", max_length=2000)


class SubmissionAnnotationIn(BaseModel):
    id: UUID | None = None
    file_id: UUID
    kind: Literal["PDF_TEXT_OR_REGION", "RICH_TEXT_RANGE"]
    mark_type: Literal["HIGHLIGHT", "UNDERLINE", "STRIKETHROUGH", "COMMENT"] | None = None
    color: Literal["YELLOW", "GREEN", "RED", "BLUE"] = "YELLOW"
    anchor: dict
    comment: str = Field("", max_length=20000)


class SubmissionFeedbackIn(BaseModel):
    revision: int = Field(ge=0)
    grade: Literal["A", "B", "C", "D", "E"]
    comment: str = Field("", max_length=20000)
    annotations: list[SubmissionAnnotationIn] = Field(default_factory=list, max_length=500)


class PeerSubmissionAssessmentIn(SubmissionAssessmentIn):
    reviewee_id: UUID


class AssignmentUpdateIn(BaseModel):
    class_id: UUID | None = None
    title: str | None = Field(None, min_length=2, max_length=100); description: str | None = Field(None, min_length=1, max_length=5000); starts_at: datetime | None = None; due_at: datetime | None = None; allow_late: bool | None = None; submitter_type: Literal["TEAM", "INDIVIDUAL"] | None = None; kind: Literal["ASSIGNMENT", "EXPERIMENT"] | None = None; version: int
    auto_review_enabled: bool | None = None
    auto_review_mode: Literal["TEAM"] | None = None
    auto_review_criteria_text: str | None = Field(None, max_length=5000)
    auto_review_due_at: datetime | None = None


class SubmissionDocumentIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SubmissionDocumentUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    markdown_content: str = Field(max_length=settings.markdown_max_bytes)


class MaterialTypeIn(BaseModel):
    material_type: Literal["TASK", "ATTACHMENT", "CRITERIA"]
