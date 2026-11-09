"""Policy library ORM models (long-term Req 31, 32).

A policy has versions. Revising creates a new draft row in the same family; approving it
retires the previous approved version. An approved version is never edited. Acknowledgements
are recorded per person against the version they read.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class PolicyKind(str, Enum):
    POLICY = "policy"
    SOP = "sop"


class PolicyDocument(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "policy_document"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # All versions of the same policy share a family id.
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=PolicyKind.POLICY.value)
    # NULL => applies to everyone.
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PolicyStatus.DRAFT.value, index=True
    )
    effective_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class PolicyAcknowledgement(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "policy_acknowledgement"
    __table_args__ = (
        UniqueConstraint("policy_id", "user_id", name="uq_policy_ack_policy_user"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policy_document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    acknowledged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssistantQueryLog(UUIDPrimaryKey, Timestamped, Base):
    """Questions asked of the HR assistant. Stores NO user identifier, so HR can see what
    people ask (and what has no answer) without tracking who asked."""

    __tablename__ = "assistant_query_log"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
