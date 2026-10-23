"""Candidates application service (Req 5.2, 5.4, 11.3).

- resolve_candidate: find an existing canonical candidate by email, or create one. When a
  near-duplicate (same email, different name) is detected, a duplicate link is recorded for
  human review rather than auto-merging.
- record_consent / withdraw_talent_pool_consent: manage explicit, purpose-specific consent.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.candidates.models import (
    Candidate,
    CandidateDuplicateLink,
    ConsentPurpose,
    ConsentRecord,
    ConsentState,
)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


@dataclass
class CandidateResolution:
    candidate: Candidate
    created: bool
    duplicate_flagged: bool


def resolve_candidate(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    full_name: str,
    email: str,
    mobile: str | None,
) -> CandidateResolution:
    normalised_email = email.strip().lower()
    stmt = select(Candidate).where(
        Candidate.organisation_id == organisation_id,
        Candidate.email == normalised_email,
    )
    existing = db.execute(stmt).scalars().first()

    if existing is not None:
        duplicate_flagged = False
        # Same email but a materially different name is flagged for human review.
        if existing.full_name.strip().lower() != full_name.strip().lower():
            db.add(
                CandidateDuplicateLink(
                    organisation_id=organisation_id,
                    candidate_id=existing.id,
                    duplicate_of_id=existing.id,
                    reason="Same email with a different name provided on a new application",
                )
            )
            db.flush()
            duplicate_flagged = True
        return CandidateResolution(existing, created=False, duplicate_flagged=duplicate_flagged)

    candidate = Candidate(
        organisation_id=organisation_id,
        full_name=full_name,
        email=normalised_email,
        mobile=mobile,
    )
    db.add(candidate)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            action="candidate.created",
            entity_type="candidate",
            entity_id=str(candidate.id),
        ),
    )
    return CandidateResolution(candidate, created=True, duplicate_flagged=False)


def get_candidate(
    db: Session, *, organisation_id: uuid.UUID, candidate_id: uuid.UUID
) -> Candidate:
    """Load a candidate, scoped to the actor's organisation (tenant isolation)."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None or candidate.organisation_id != organisation_id:
        raise NotFoundError("Candidate not found")
    return candidate


def reveal_contact(
    db: Session, *, organisation_id: uuid.UUID, candidate_id: uuid.UUID, actor_id: uuid.UUID
) -> Candidate:
    """Return a candidate for UNMASKED contact display and audit the access.

    This is the single choke point for revealing candidate PII. The permission check
    (``candidate.view_pii``) is enforced at the router; here we record who accessed the
    contact details and when, so every reveal is traceable (security.md). No PII is written
    into the audit payload itself — only a reference to the candidate.
    """
    candidate = get_candidate(db, organisation_id=organisation_id, candidate_id=candidate_id)
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="candidate.contact_revealed",
            entity_type="candidate",
            entity_id=str(candidate.id),
            security_context="candidate_pii_access",
        ),
    )
    return candidate


def record_consent(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    candidate_id: uuid.UUID,
    purpose: ConsentPurpose,
    notice_version: str,
) -> ConsentRecord:
    consent = ConsentRecord(
        organisation_id=organisation_id,
        candidate_id=candidate_id,
        purpose=purpose.value,
        state=ConsentState.GRANTED.value,
        notice_version=notice_version,
        granted_at=_now(),
    )
    db.add(consent)
    if purpose is ConsentPurpose.TALENT_POOL:
        candidate = db.get(Candidate, candidate_id)
        if candidate is not None:
            candidate.in_talent_pool = True
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            action="consent.granted",
            entity_type="consent_record",
            entity_id=str(consent.id),
            reason=f"purpose={purpose.value}; notice={notice_version}",
        ),
    )
    return consent


def withdraw_talent_pool_consent(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    candidate_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Withdraw talent-pool consent (Req 11.3, AC-16)."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None or candidate.organisation_id != organisation_id:
        raise NotFoundError("Candidate not found")

    stmt = select(ConsentRecord).where(
        ConsentRecord.organisation_id == organisation_id,
        ConsentRecord.candidate_id == candidate_id,
        ConsentRecord.purpose == ConsentPurpose.TALENT_POOL.value,
        ConsentRecord.state == ConsentState.GRANTED.value,
    )
    for record in db.execute(stmt).scalars():
        record.state = ConsentState.WITHDRAWN.value
        record.withdrawn_at = _now()
    candidate.in_talent_pool = False
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="consent.talent_pool_withdrawn",
            entity_type="candidate",
            entity_id=str(candidate_id),
        ),
    )
