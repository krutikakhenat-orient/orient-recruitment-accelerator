"""Tests for the append-only audit event hash chain (Req 13.1)."""

from __future__ import annotations

import pytest

from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event, verify_chain
from tests.factories import make_org


def test_chain_links_and_verifies(db_session) -> None:
    org = make_org(db_session)
    for i in range(3):
        record_event(
            db_session,
            AuditEventWrite(
                organisation_id=org.id,
                action=f"test.event.{i}",
                entity_type="test",
                entity_id=str(i),
            ),
        )
    db_session.flush()
    assert verify_chain(db_session, org.id) is True


def test_tampering_breaks_chain(db_session) -> None:
    org = make_org(db_session)
    first = record_event(
        db_session,
        AuditEventWrite(organisation_id=org.id, action="a", entity_type="t", entity_id="1"),
    )
    record_event(
        db_session,
        AuditEventWrite(organisation_id=org.id, action="b", entity_type="t", entity_id="2"),
    )
    db_session.flush()

    # Tamper with a stored event's content without recomputing the hash.
    first.reason = "mutated after the fact"
    db_session.flush()
    assert verify_chain(db_session, org.id) is False


def test_rejects_sensitive_content_in_reason(db_session) -> None:
    org = make_org(db_session)
    with pytest.raises(ValueError, match="password"):
        record_event(
            db_session,
            AuditEventWrite(
                organisation_id=org.id,
                action="x",
                entity_type="t",
                reason="user password was hunter2",
            ),
        )
