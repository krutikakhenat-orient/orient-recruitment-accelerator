"""Hiring decision ORM model (Req 10.4).

Records the final disposition (select/reject/hold/withdraw) with a recommend step and an
approve step, each with actor and reason. The actual application state change is performed
by the application transition service; this record is the decision's documentation.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class DecisionType(str, Enum):
    SELECT = "select"
    REJECT = "reject"
    HOLD = "hold"
    WITHDRAW = "withdraw"


class DecisionStatus(str, Enum):
    RECOMMENDED = "recommended"
    APPROVED = "approved"


class HiringDecision(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "hiring_decision"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    decision_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DecisionStatus.RECOMMENDED.value
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    recommended_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
