"""SLA API schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class SlaPolicyRead(BaseModel):
    campaign_id: uuid.UUID | None
    name: str
    window_hours: int
    at_risk_percent: int
    # "campaign" | "organisation" | "built_in"
    source: str


class SlaPolicyUpdate(BaseModel):
    campaign_id: uuid.UUID | None = None
    window_hours: int = Field(ge=1, le=720)
    at_risk_percent: int = Field(ge=1, le=99)


class SlaItemRead(BaseModel):
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_name: str
    state: str
    status: str  # on_track | at_risk | overdue | paused
    hours_elapsed: float
    hours_remaining: float
    started_at: dt.datetime


class SlaSummaryRead(BaseModel):
    window_hours: int
    on_track: int
    at_risk: int
    overdue: int
    paused: int
    completed: int
    note: str


class SlaRunResult(BaseModel):
    reminders_recorded: int
    overdue_recorded: int
    messages: list[str]
