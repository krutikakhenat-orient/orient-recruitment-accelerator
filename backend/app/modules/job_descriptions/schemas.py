"""Job Description Pydantic schemas."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JDVersionUpdate(BaseModel):
    """Human review edits to a draft JD version (authoritative structured content)."""

    position_title: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    work_mode: str | None = Field(default=None, max_length=64)
    employment_type: str | None = Field(default=None, max_length=64)
    number_of_openings: int | None = Field(default=None, ge=1, le=1000)
    minimum_total_experience_years: float | None = Field(default=None, ge=0, le=60)
    minimum_relevant_experience_years: float | None = Field(default=None, ge=0, le=60)
    responsibilities: list[str] | None = None
    mandatory_skills: list[str] | None = None
    desirable_skills: list[str] | None = None


class JDApprove(BaseModel):
    change_reason: str = Field(min_length=1, max_length=1000)


class ProposedFieldRead(BaseModel):
    name: str
    value: str
    confidence: float
    source_span: str


class JDVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_description_id: uuid.UUID
    version_number: int
    status: str
    source_document_id: uuid.UUID | None
    position_title: str | None
    department: str | None
    location: str | None
    work_mode: str | None
    employment_type: str | None
    number_of_openings: int | None
    minimum_total_experience_years: float | None
    minimum_relevant_experience_years: float | None
    responsibilities: list[str]
    mandatory_skills: list[str]
    desirable_skills: list[str]
    extraction_draft: dict[str, Any] | None
    approved_at: dt.datetime | None
    change_reason: str | None
