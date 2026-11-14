"""Policy library schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.policies.audience import normalise_audience

_KIND = "^(policy|sop|faq)$"


class PolicyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="policy", pattern=_KIND)
    department: str | None = Field(default=None, max_length=120)
    body: str = Field(min_length=1, max_length=20000)
    effective_date: dt.date | None = None
    review_due_date: dt.date | None = None
    audience: list[str] | None = Field(default=None, max_length=10)
    # Publish and sync at once (default). false = keep as a draft ("Save as draft").
    publish: bool = True

    @field_validator("audience")
    @classmethod
    def _audience(cls, value: list[str] | None) -> list[str] | None:
        return normalise_audience(value)


class PolicyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    effective_date: dt.date | None = None
    review_due_date: dt.date | None = None
    audience: list[str] | None = Field(default=None, max_length=10)

    @field_validator("audience")
    @classmethod
    def _audience(cls, value: list[str] | None) -> list[str] | None:
        return normalise_audience(value)


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    family_id: uuid.UUID
    title: str
    kind: str
    department: str | None
    body: str
    version: int
    status: str
    effective_date: dt.date | None
    review_due_date: dt.date | None = None
    updated_at: dt.datetime
    audience: list[str] = Field(default_factory=lambda: ["everyone"])
    index_status: str = "not_indexed"
    index_error: str | None = None
    indexed_at: dt.datetime | None = None
    source_filename: str | None = None
    has_file: bool = False
    acknowledged: bool = False
    acknowledgement_count: int = 0

    @field_validator("audience", mode="before")
    @classmethod
    def _default_audience(cls, value: object) -> object:
        return value or ["everyone"]


class DuplicateRef(BaseModel):
    id: uuid.UUID
    title: str
    version: int
    status: str


class IndexStatusRead(BaseModel):
    policy_id: uuid.UUID
    status: str
    index_status: str
    index_error: str | None
    indexed_at: dt.datetime | None
    ingestion_job_id: str | None
    backend: str
