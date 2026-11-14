"""HR question inbox schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class HrQuestionRead(BaseModel):
    """Asker's own view: no internal fields beyond the answer."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    contact_preference: str
    status: str
    answer: str | None
    answered_at: dt.datetime | None
    created_at: dt.datetime


class HrQuestionInboxRead(HrQuestionRead):
    """HR view: includes who asked, so HR can reply."""

    asked_by: uuid.UUID
    asked_by_name: str | None = None
    asked_by_email: str | None = None


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=2, max_length=4000)
