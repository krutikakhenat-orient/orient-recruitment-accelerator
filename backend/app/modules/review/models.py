"""Human-review queue models (Req 9.1).

A ReviewItem is a work item surfaced for a reviewer (missing evidence, conflict, low
confidence, borderline score, duplicate, exception request, alternative-role match).
ReviewAction records each reviewer decision; corrections store the original and corrected
values plus reason/actor/timestamp and never silently alter source records.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class ReviewReason(str, Enum):
    UNVERIFIED_VALUE = "unverified_value"
    MISSING_MANDATORY_EVIDENCE = "missing_mandatory_evidence"
    CONFLICTING_VALUE = "conflicting_value"
    LOW_CONFIDENCE = "low_confidence"
    BORDERLINE_SCORE = "borderline_score"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    EXCEPTION_REQUEST = "exception_request"
    ALTERNATIVE_ROLE_MATCH = "alternative_role_match"


class ReviewItemStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    # Automatically closed because a newer screening run replaced this item's findings.
    # Distinct from RESOLVED (a reviewer disposition) so the audit trail shows the item was
    # retired by re-screening, not acted on by a human.
    SUPERSEDED = "superseded"


class ReviewActionType(str, Enum):
    CONFIRM_EVIDENCE = "confirm_evidence"
    CORRECT_VALUE = "correct_value"
    REQUEST_CLARIFICATION = "request_clarification"
    RECOMMEND_INTERVIEW = "recommend_interview"
    RECOMMEND_WAITLIST = "recommend_waitlist"
    RECOMMEND_ALTERNATIVE_CAMPAIGN = "recommend_alternative_campaign"
    ESCALATE_HIRING_MANAGER = "escalate_hiring_manager"
    SUBMIT_EXCEPTION = "submit_exception"


class ReviewItem(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "review_item"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ReviewItemStatus.OPEN.value
    )
    screening_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    actions: Mapped[list[ReviewAction]] = relationship(
        back_populates="item", cascade="all, delete-orphan", lazy="selectin"
    )


class ReviewAction(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "review_action"

    review_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # For corrections: the original and corrected values are both preserved (Req 9.1).
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resolves_item: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    item: Mapped[ReviewItem] = relationship(back_populates="actions")
