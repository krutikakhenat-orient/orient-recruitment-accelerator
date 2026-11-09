"""SLA ORM models (long-term Req 24).

SlaPolicy: how long a recruiter has to reach a shortlisting outcome (default 48 hours) and
when an application is "at risk" (default 75% of the window). A policy with no campaign is
the organisation default. SlaEscalation records each reminder / overdue notice so it is
sent once per level and is auditable.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class EscalationLevel(str, Enum):
    REMINDER = "reminder"
    OVERDUE = "overdue"


class SlaPolicy(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "sla_policy"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL => the organisation-wide default.
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Shortlisting target")
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=48)
    at_risk_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SlaEscalation(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "sla_escalation"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
