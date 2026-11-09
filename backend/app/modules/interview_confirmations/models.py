"""Interview confirmation link ORM model (long-term Req 22).

One row per link issued for an interview invitation. Only a SHA-256 hash of the token is
stored, so a database leak does not expose working links. A link answers once and expires.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class InterviewConfirmationLink(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "interview_confirmation_link"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_invitation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # confirmed | declined | reschedule_requested
    response: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
