"""Candidate journey HTTP router (thin, read-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.journey import service
from app.modules.journey.schemas import JourneyRead

router = APIRouter(prefix="/api/v1/journey", tags=["journey"])


@router.get("/applications/{application_id}", response_model=JourneyRead)
def application_journey(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> JourneyRead:
    """Where this candidate is in the whole process and what happens next.
    Needs candidate.view for the candidate's campaign."""
    application = application_service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, application.campaign_id)
    return service.journey_for(db, actor.organisation_id, application)
