"""Onboarding ORM models (long-term Req 26-29, 34).

Data minimisation: onboarding data exists only for candidates who were SELECTED, and is never
read by screening. The document records keep metadata a person types in (name shown on the
document, expiry date). Identity NUMBERS are deliberately not stored.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class OfferStatus(str, Enum):
    DRAFTED = "drafted"
    APPROVED = "approved"
    ISSUED = "issued"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


ACTIVE_OFFER_STATUSES: frozenset[str] = frozenset(
    {OfferStatus.DRAFTED.value, OfferStatus.APPROVED.value, OfferStatus.ISSUED.value}
)


class CaseStatus(str, Enum):
    DOCUMENTS_PENDING = "documents_pending"
    DOCUMENTS_IN_REVIEW = "documents_in_review"
    READY_TO_JOIN = "ready_to_join"
    JOINED = "joined"
    WITHDRAWN = "withdrawn"


class DocStatus(str, Enum):
    REQUESTED = "requested"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    CORRECTION_REQUESTED = "correction_requested"
    WAIVED = "waived"


class FlagKind(str, Enum):
    MISSING = "missing"
    MISMATCH = "mismatch"
    EXPIRED = "expired"
    NEEDS_DETAILS = "needs_details"


class FlagStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CORRECTION_REQUESTED = "correction_requested"
    WAIVED = "waived"


class Offer(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "offer"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OfferStatus.DRAFTED.value, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    respond_by: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OnboardingCase(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "onboarding_case"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=CaseStatus.DOCUMENTS_PENDING.value, index=True
    )
    joining_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    reporting_manager: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_expectations: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HR must approve the pre-joining / welcome wording for this joiner before it is sent.
    content_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    joined_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OnboardingDocument(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "onboarding_document"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("onboarding_case.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DocStatus.REQUESTED.value
    )
    received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    name_on_document: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class OnboardingDocumentFlag(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "onboarding_document_flag"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("onboarding_case.id", ondelete="CASCADE"), nullable=False, index=True
    )
    onboarding_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=FlagStatus.OPEN.value, index=True
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="rule_based")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
