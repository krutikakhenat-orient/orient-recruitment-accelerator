"""Audit service: records append-only events with a per-organisation hash chain.

Every sensitive action records an event through :func:`record_event`. The service
computes an integrity hash over the event content plus the previous event's hash so
the chain is tamper-evident (Req 13.1). The service never logs PII and refuses to
store passwords, tokens, or resume content (callers pass references, not content).
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id
from app.modules.audit.models import AuditEvent
from app.modules.audit.schemas import AuditEventWrite

_FORBIDDEN_SUBSTRINGS = ("password", "secret", "token", "resume_text")


def _canonical_payload(event: AuditEventWrite, sequence: int, previous_hash: str | None) -> str:
    return json.dumps(
        {
            "organisation_id": str(event.organisation_id),
            "sequence": sequence,
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "actor_role": event.actor_role,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "previous_state_ref": event.previous_state_ref,
            "new_state_ref": event.new_state_ref,
            "reason": event.reason,
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _assert_no_sensitive_content(event: AuditEventWrite) -> None:
    reason = (event.reason or "").lower()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        if forbidden in reason:
            raise ValueError(f"Audit reason must not contain '{forbidden}' content")


def _last_event(db: Session, organisation_id: uuid.UUID) -> AuditEvent | None:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.organisation_id == organisation_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def record_event(db: Session, event: AuditEventWrite) -> AuditEvent:
    _assert_no_sensitive_content(event)

    previous = _last_event(db, event.organisation_id)
    sequence = (previous.sequence + 1) if previous else 1
    previous_hash = previous.integrity_hash if previous else None

    payload = _canonical_payload(event, sequence, previous_hash)
    integrity_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    row = AuditEvent(
        organisation_id=event.organisation_id,
        sequence=sequence,
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        previous_state_ref=event.previous_state_ref,
        new_state_ref=event.new_state_ref,
        reason=event.reason,
        correlation_id=get_correlation_id(),
        security_context=event.security_context,
        previous_hash=previous_hash,
        integrity_hash=integrity_hash,
    )
    db.add(row)
    db.flush()
    return row


def verify_chain(db: Session, organisation_id: uuid.UUID) -> bool:
    """Recompute the hash chain and confirm it is intact. Used by audit tooling/tests."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.organisation_id == organisation_id)
        .order_by(AuditEvent.sequence.asc())
    )
    previous_hash: str | None = None
    for row in db.execute(stmt).scalars():
        payload = _canonical_payload(
            AuditEventWrite(
                organisation_id=row.organisation_id,
                actor_id=row.actor_id,
                actor_role=row.actor_role,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                previous_state_ref=row.previous_state_ref,
                new_state_ref=row.new_state_ref,
                reason=row.reason,
            ),
            row.sequence,
            previous_hash,
        )
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if expected != row.integrity_hash or row.previous_hash != previous_hash:
            return False
        previous_hash = row.integrity_hash
    return True
