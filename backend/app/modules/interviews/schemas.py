"""Interview Pydantic schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class StageCreate(BaseModel):
    campaign_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    sequence: int = Field(default=1, ge=1)


class StageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    sequence: int


class SlotCreate(BaseModel):
    stage_id: uuid.UUID
    slot_date: dt.date
    start_time: str = Field(min_length=1, max_length=16)
    location: str | None = Field(default=None, max_length=255)
    mode: str = "in_person"
    capacity: int = Field(default=1, ge=1, le=100)


class SlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage_id: uuid.UUID
    slot_date: dt.date
    start_time: str
    location: str | None
    mode: str
    capacity: int
    confirmed_count: int


class InvitationApprove(BaseModel):
    application_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    # Optional justification. Required by the router when selecting a below-threshold
    # candidate from the Review Queue (a screening override), recorded in the audit trail.
    reason: str | None = Field(default=None, max_length=1000)


class SlotAssign(BaseModel):
    slot_id: uuid.UUID


class AttendanceRequest(BaseModel):
    attended: bool


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    stage_id: uuid.UUID | None
    slot_id: uuid.UUID | None
    status: str
    attendance: str
    auto_invite: bool
