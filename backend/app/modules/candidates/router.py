"""Candidates HTTP router.

Talent-pool consent withdrawal (Req 11.3, AC-16) is exposed as a privacy action requiring
``privacy_request.manage``. Candidate self-service withdrawal arrives with candidate
authentication in a later phase; the underlying service is identical.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.db.session import get_db
from app.modules.candidates import service
from app.modules.candidates.schemas import CandidateContactRead, CandidateRead
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/candidates", tags=["candidates"])


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.CANDIDATE_VIEW)),
) -> CandidateRead:
    """Candidate profile with contact PII MASKED. Requires candidate.view."""
    candidate = service.get_candidate(
        db, organisation_id=actor.organisation_id, candidate_id=candidate_id
    )
    return CandidateRead.from_candidate(candidate)


@router.get("/{candidate_id}/contact", response_model=CandidateContactRead)
def reveal_candidate_contact(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.CANDIDATE_VIEW_PII)),
) -> CandidateContactRead:
    """Reveal a candidate's UNMASKED contact details (email/phone/LinkedIn).

    Requires the elevated candidate.view_pii permission. Every reveal is recorded in the
    audit trail (security.md): the service emits a ``candidate.contact_revealed`` event.
    """
    candidate = service.reveal_contact(
        db,
        organisation_id=actor.organisation_id,
        candidate_id=candidate_id,
        actor_id=actor.user_id,
    )
    return CandidateContactRead.model_validate(candidate)


@router.post("/{candidate_id}/talent-pool/withdraw", status_code=204, response_class=Response)
def withdraw_talent_pool(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.PRIVACY_REQUEST_MANAGE)),
) -> Response:
    service.withdraw_talent_pool_consent(
        db,
        organisation_id=actor.organisation_id,
        candidate_id=candidate_id,
        actor_id=actor.user_id,
    )
    return Response(status_code=204)
