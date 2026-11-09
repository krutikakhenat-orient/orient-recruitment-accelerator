"""Policy library and assistant schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class PolicyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="policy", pattern="^(policy|sop)$")
    department: str | None = Field(default=None, max_length=120)
    body: str = Field(min_length=1, max_length=20000)
    effective_date: dt.date | None = None


class PolicyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    effective_date: dt.date | None = None


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
    updated_at: dt.datetime
    acknowledged: bool = False
    acknowledgement_count: int = 0


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=300)


class AnswerSource(BaseModel):
    policy_id: uuid.UUID
    title: str
    version: int


class AskResponse(BaseModel):
    answered: bool
    answer: str
    sources: list[AnswerSource]
    route_to_hr: bool
    note: str


class UnansweredRead(BaseModel):
    question: str
    asked_at: dt.datetime
