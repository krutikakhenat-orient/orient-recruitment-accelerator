"""Rules & thresholds ORM models (Req 7.1, 7.2).

A RuleSet belongs to a campaign and has one or more RuleSetVersions. An approved
RuleSetVersion is IMMUTABLE (its rules JSON is frozen). Thresholds are versioned the same
way; a ThresholdVersion captures the numeric cut-offs used by screening. Separation of
duties (creator != sole approver) and four-eyes threshold changes are enforced in the
service layer.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class ApprovalStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RuleSet(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "rule_set"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    versions: Mapped[list[RuleSetVersion]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan", lazy="selectin"
    )


class RuleSetVersion(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "rule_set_version"

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule_set.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApprovalStatus.DRAFT.value
    )

    # The validated typed-JSON rules (frozen on approval).
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    rule_set: Mapped[RuleSet] = relationship(back_populates="versions")

    @property
    def is_approved(self) -> bool:
        return self.status == ApprovalStatus.APPROVED.value


class ThresholdSet(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "threshold_set"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    # Whether four-eyes (distinct approver) is required for threshold changes.
    four_eyes_required: Mapped[bool] = mapped_column(nullable=False, default=True)

    versions: Mapped[list[ThresholdVersion]] = relationship(
        back_populates="threshold_set", cascade="all, delete-orphan", lazy="selectin"
    )


class ThresholdVersion(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "threshold_version"

    threshold_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("threshold_set.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApprovalStatus.DRAFT.value
    )

    # Fit-score cut-offs (0..100). Below review_below -> waitlist/review; at/above
    # recommend_at_or_above -> eligible for interview recommendation (still human-approved).
    review_below: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    recommend_at_or_above: Mapped[float] = mapped_column(Float, nullable=False, default=70.0)

    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=False, default="")

    threshold_set: Mapped[ThresholdSet] = relationship(back_populates="versions")

    @property
    def is_approved(self) -> bool:
        return self.status == ApprovalStatus.APPROVED.value
