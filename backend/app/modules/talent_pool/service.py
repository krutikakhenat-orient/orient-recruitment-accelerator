"""Talent-pool service (Req 11.3).

Search is restricted to candidates with ACTIVE talent-pool consent. A match is only a
SUGGESTION: a recruiter must verify evidence before contacting the candidate, so this
service never initiates candidate communication. Talent-pool access is audited.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.candidates.models import (
    Candidate,
    ConsentPurpose,
    ConsentRecord,
    ConsentState,
)


@dataclass
class TalentMatch:
    candidate_id: uuid.UUID
    full_name: str
    email: str
    # A match is advisory only; evidence must be verified before contact.
    note: str = "Potential historical match. Verify evidence before contacting."


def search(
    db: Session, *, organisation_id: uuid.UUID, actor_id: uuid.UUID, skill_token: str
) -> list[TalentMatch]:
    """Return consented talent-pool candidates. Access is audited (talent_pool access)."""
    # Only candidates with an active talent-pool consent are eligible.
    consented_ids = set(
        db.execute(
            select(ConsentRecord.candidate_id).where(
                ConsentRecord.organisation_id == organisation_id,
                ConsentRecord.purpose == ConsentPurpose.TALENT_POOL.value,
                ConsentRecord.state == ConsentState.GRANTED.value,
            )
        ).scalars()
    )
    matches: list[TalentMatch] = []
    if consented_ids:
        candidates = db.execute(
            select(Candidate).where(
                Candidate.organisation_id == organisation_id,
                Candidate.id.in_(consented_ids),
                Candidate.in_talent_pool.is_(True),
            )
        ).scalars()
        matches = [
            TalentMatch(candidate_id=c.id, full_name=c.full_name, email=c.email)
            for c in candidates
        ]

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action="talent_pool.searched", entity_type="talent_pool",
            entity_id=None, reason=f"query_skill={skill_token}; matches={len(matches)}",
        ),
    )
    return matches
