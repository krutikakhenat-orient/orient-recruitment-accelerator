"""Notification API schemas (never serialise ORM objects directly)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ChannelStatus(BaseModel):
    mode: str
    state: str  # not_configured | simulated | live
    message: str


class NotificationStatusRead(BaseModel):
    email: ChannelStatus
    whatsapp: ChannelStatus


class TemplateRead(BaseModel):
    key: str
    label: str
    audience: str
    description: str
    subject: str
    body: str
    version: int
    placeholders: list[str]
    is_built_in: bool


class TemplateUpdate(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=5000)


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID | None
    application_id: uuid.UUID | None
    onboarding_case_id: uuid.UUID | None
    template_key: str
    template_version: int
    channel: str
    recipient: str
    subject: str | None
    body: str
    status: str
    failure_reason: str | None
    manual_link: str | None
    created_at: dt.datetime


class SendRequest(BaseModel):
    application_id: uuid.UUID
    template_key: str = Field(min_length=1, max_length=64)
    channel: str = Field(default="email", pattern="^(email|whatsapp)$")
