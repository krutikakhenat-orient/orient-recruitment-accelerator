"""Candidate ORM models (Req 5.2, 11.3).

A Candidate is the canonical individual profile, kept separate from Applications so that
updating the master profile never rewrites historical application answers. Consent is
modelled explicitly, with a SEPARATE talent-pool consent (Req 11.3). Potential duplicates
are recorded as links for human review rather than auto-merged (Req 5.4).
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, OptimisticVersion, Timestamped, UUIDPrimaryKey


class ConsentPurpose(str, Enum):
    APPLICATION = "application"       # processing this application
    TALENT_POOL = "talent_pool"       # separate, explicit opt-in


class ConsentState(str, Enum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class Candidate(UUIDPrimaryKey, Timestamped, Actioned, OptimisticVersion, Base):
    __tablename__ = "candidate"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Canonical contact details. A lowercased email is used for duplicate heuristics.
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linkedin: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Talent-pool status is a convenience flag derived from the latest TALENT_POOL consent.
    in_talent_pool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ConsentRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "consent_record"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConsentState.GRANTED.value
    )
    notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateDuplicateLink(UUIDPrimaryKey, Timestamped, Base):
    """A suspected duplicate pairing, surfaced for human review (never auto-merged)."""

    __tablename__ = "candidate_duplicate_link"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    duplicate_of_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
