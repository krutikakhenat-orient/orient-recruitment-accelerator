"""Append-only audit event model with a per-event hash chain (Req 13.1).

Tamper-evidence strategy (default per the Open Decisions register): each event stores
a ``integrity_hash`` computed over its canonical content plus the previous event's hash
within the same organisation. Breaking any earlier event invalidates the chain.

Audit rows are never updated or deleted by application code.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, UUIDPrimaryKey


class AuditEvent(UUIDPrimaryKey, Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        UniqueConstraint("organisation_id", "sequence", name="uq_audit_org_sequence"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Monotonic sequence within an organisation, used to order the hash chain.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    previous_state_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    new_state_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    security_context: Mapped[str | None] = mapped_column(String(255), nullable=True)

    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
