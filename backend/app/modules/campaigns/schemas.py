"""Campaign Pydantic schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    position_title: str = Field(min_length=1, max_length=255)
    campaign_type: str | None = Field(default=None, max_length=64)
    number_of_openings: int = Field(default=1, ge=1, le=1000)
    employment_type: str | None = Field(default=None, max_length=64)
    work_location: str | None = Field(default=None, max_length=255)
    work_mode: str | None = Field(default=None, max_length=64)
    application_opening_date: dt.date | None = None
    application_closing_date: dt.date | None = None


class CampaignTransitionRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=1000)


class CampaignAssignRequest(BaseModel):
    """Assign a staff user to a campaign. Provide an email, or omit to self-assign."""

    email: str | None = Field(default=None, max_length=320)


class ClosureReadinessRead(BaseModel):
    """Advisory counts of in-flight work before a campaign is completed/cancelled.

    ``has_pending`` is True when either count is non-zero; the UI uses it to warn HR before
    final closure. These counts never block a transition.
    """

    pending_applications: int
    pending_interviews: int
    has_pending: bool


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    position_title: str
    number_of_openings: int
    state: str
    approved_jd_version_id: uuid.UUID | None
    approved_rule_set_version_id: uuid.UUID | None
    approved_form_version_id: uuid.UUID | None
    active_threshold_version_id: uuid.UUID | None
    privacy_notice_version: str | None
    version: int


class PublicRoleRead(BaseModel):
    """A single open role for the public, unauthenticated careers list.

    Deliberately minimal: only what a candidate needs to choose a role. It exposes NO
    internal fields (no org id, project id, state, version pointers, counts, JD content or
    screening config) to keep this new public surface a small, safe attack surface
    (security.md: enumeration / excessive data exposure).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    location: str | None
    employment_type: str | None
    work_mode: str | None
