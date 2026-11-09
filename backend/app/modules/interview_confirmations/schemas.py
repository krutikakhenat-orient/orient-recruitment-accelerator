"""Interview confirmation schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.modules.notifications.schemas import DeliveryRead


class LinkIssued(BaseModel):
    url: str
    expires_at: dt.datetime
    delivery: DeliveryRead | None


class LinkStatus(BaseModel):
    has_link: bool
    # none | open | answered | expired
    state: str
    response: str | None
    responded_at: dt.datetime | None
    expires_at: dt.datetime | None
    invitation_status: str
    message: str


class SuggestedSlot(BaseModel):
    slot_id: uuid.UUID
    stage_name: str
    slot_date: dt.date
    start_time: str
    location: str | None
    mode: str
    remaining: int


class PublicPreview(BaseModel):
    # open | answered | expired
    state: str
    first_name: str
    role_title: str
    when: str
    where: str
    mode: str
    message: str


class PublicRespond(BaseModel):
    response: str = Field(pattern="^(confirmed|declined|reschedule_requested)$")


class PublicResult(BaseModel):
    response: str
    message: str
