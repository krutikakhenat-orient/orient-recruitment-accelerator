"""Candidate journey schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class JourneyStage(BaseModel):
    key: str
    label: str
    description: str
    owner: str
    # done | current | upcoming | blocked | skipped
    status: str
    optional: bool = False
    detail: str | None = None
    at: dt.datetime | None = None


class JourneyRead(BaseModel):
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_name: str
    role_title: str
    application_state: str
    current_stage: str | None
    next_step: str
    closed: bool
    stages: list[JourneyStage]
