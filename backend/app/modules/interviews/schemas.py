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
    checked_in_at: dt.datetime | None = None
    checked_out_at: dt.datetime | None = None
    auto_invite: bool


# --- Interviewer assignments (panel isolation) ----------------------------------------
class AssignmentCreate(BaseModel):
    """Assign an interviewer to a campaign and optional stage. The campaign is taken from
    the path; the organisation and assigner are derived from the authenticated session and
    never from the client."""

    interviewer_id: uuid.UUID
    stage_id: uuid.UUID | None = None


class AssignmentUpdate(BaseModel):
    """Supported scope change: move the assignment to a stage (or whole-campaign = null).
    The interviewer and campaign are immutable."""

    stage_id: uuid.UUID | None = None


class AssignmentRead(BaseModel):
    """Assignment METADATA only — never candidate profiles, resumes, scores, or scorecards.
    ``interviewer_name`` is the panel member's display name for the management UI."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    campaign_id: uuid.UUID
    stage_id: uuid.UUID | None
    interviewer_id: uuid.UUID
    interviewer_name: str | None = None
    assigned_by: uuid.UUID
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class MyAssignmentRead(BaseModel):
    """One of the authenticated interviewer's own active assignments (drives the panel
    campaign-bucket list). Campaign id is the stable grouping key; name is a display label."""

    campaign_id: uuid.UUID
    campaign_name: str
    stage_id: uuid.UUID | None = None
    stage_name: str | None = None


class AssignmentOverviewRead(BaseModel):
    """One interviewer assignment, enriched with display labels, for the System Admin
    overview table. METADATA ONLY — deliberately carries no candidate information
    (no profiles, resumes, contact details, scores, rankings, or assessments)."""

    id: uuid.UUID
    interviewer_id: uuid.UUID
    interviewer_name: str | None = None
    interviewer_email: str | None = None
    interviewer_role_names: list[str] = Field(default_factory=list)
    campaign_id: uuid.UUID
    campaign_name: str | None = None
    stage_id: uuid.UUID | None = None
    stage_name: str | None = None
    is_active: bool
