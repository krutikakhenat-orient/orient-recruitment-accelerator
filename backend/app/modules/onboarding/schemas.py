"""Onboarding and offer API schemas."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.notifications.schemas import DeliveryRead

# ---------------------------------------------------------------- offers


class OfferCreate(BaseModel):
    application_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=2000)
    respond_by: dt.date | None = None


class OfferRespond(BaseModel):
    outcome: str = Field(pattern="^(accepted|declined)$")


class OfferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    status: str
    notes: str | None
    respond_by: dt.date | None
    approved_at: dt.datetime | None
    issued_at: dt.datetime | None
    responded_at: dt.datetime | None
    created_at: dt.datetime
    candidate_name: str | None = None
    # Present on actions that send a message.
    delivery: DeliveryRead | None = None


# ------------------------------------------------------------- onboarding


class CaseCreate(BaseModel):
    application_id: uuid.UUID
    joining_date: dt.date | None = None
    reporting_manager: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    work_location: str | None = Field(default=None, max_length=255)
    role_expectations: str | None = Field(default=None, max_length=2000)


class CaseUpdate(BaseModel):
    joining_date: dt.date | None = None
    reporting_manager: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    work_location: str | None = Field(default=None, max_length=255)
    role_expectations: str | None = Field(default=None, max_length=2000)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    required: bool
    status: str
    received_at: dt.datetime | None
    name_on_document: str | None
    expiry_date: dt.date | None
    note: str | None


class FlagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    onboarding_document_id: uuid.UUID | None
    kind: str
    message: str
    status: str
    source: str
    resolution_reason: str | None


class CaseRead(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_name: str
    role_title: str
    status: str
    joining_date: dt.date | None
    reporting_manager: str | None
    department: str | None
    work_location: str | None
    role_expectations: str | None
    content_approved: bool
    documents_total: int
    documents_done: int
    open_flags: int
    created_at: dt.datetime


class CaseDetailRead(CaseRead):
    documents: list[DocumentRead]
    flags: list[FlagRead]
    ai_verification_note: str


class CaseCreated(BaseModel):
    case: CaseRead
    delivery: DeliveryRead | None


class DocumentReceive(BaseModel):
    name_on_document: str | None = Field(default=None, max_length=255)
    expiry_date: dt.date | None = None
    note: str | None = Field(default=None, max_length=500)


class DocumentStatusSet(BaseModel):
    status: str = Field(pattern="^(accepted|waived|correction_requested|requested)$")
    note: str | None = Field(default=None, max_length=500)


class FlagResolve(BaseModel):
    action: str = Field(pattern="^(accepted|correction_requested|waived)$")
    reason: str = Field(min_length=1, max_length=500)


class AnnouncementRequest(BaseModel):
    recipients: list[EmailStr] = Field(min_length=1, max_length=25)
    # HR confirms the joiner agreed to be announced (name, role and team only).
    joiner_agreed: bool


class MessagesSent(BaseModel):
    deliveries: list[DeliveryRead]


class HrmsPreviewRead(BaseModel):
    provider: str
    state: str
    message: str
    record: dict[str, Any]
