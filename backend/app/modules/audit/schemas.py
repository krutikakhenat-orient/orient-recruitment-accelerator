"""Audit API/request schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class AuditEventWrite(BaseModel):
    """Internal input used by services to record an audit event."""

    organisation_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    previous_state_ref: str | None = None
    new_state_ref: str | None = None
    reason: str | None = None
    security_context: str | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    sequence: int
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str | None
    reason: str | None
    correlation_id: str | None
    occurred_at: dt.datetime
    integrity_hash: str
