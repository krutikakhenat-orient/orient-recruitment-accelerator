"""Notification ORM models (Req 12.1, long-term Req 21).

NotificationTemplate is versioned: editing creates a new version and deactivates the
previous one. NotificationDelivery records every attempt with an HONEST status:

  sent         - a real provider accepted the message
  simulated    - local demo mode; nothing was actually delivered
  unconfigured - no provider is set up; a manual-send link is stored instead
  failed       - a provider was tried and rejected it

Internal scores and recruiter notes are never part of a message (see service guard).
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class DeliveryStatus(str, Enum):
    SENT = "sent"
    SIMULATED = "simulated"
    UNCONFIGURED = "unconfigured"
    FAILED = "failed"


class Channel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class NotificationTemplate(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "notification_template"
    __table_args__ = (
        UniqueConstraint("organisation_id", "key", "version", name="uq_notification_template_ver"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NotificationDelivery(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "notification_delivery"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    onboarding_case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    provider_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manual_link: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
