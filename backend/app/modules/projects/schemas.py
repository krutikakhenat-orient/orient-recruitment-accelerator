"""Projects Pydantic schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    business_unit: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    business_owner: str | None = Field(default=None, max_length=255)
    hr_owner: str | None = Field(default=None, max_length=255)
    description: str | None = None
    planned_hiring_start: dt.date | None = None
    planned_hiring_end: dt.date | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    business_unit: str | None
    department: str | None
    business_owner: str | None
    hr_owner: str | None
    description: str | None
    planned_hiring_start: dt.date | None
    planned_hiring_end: dt.date | None
    status: str
    version: int
