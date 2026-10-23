"""Form schema HTTP router (thin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.campaigns import service as campaign_service
from app.modules.forms import service
from app.modules.forms.schemas import FormDraftCreate, FormVersionRead
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/forms", tags=["forms"])


@router.post("/drafts", response_model=FormVersionRead, status_code=201)
def create_draft(
    payload: FormDraftCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> FormVersionRead:
    require_campaign_permission(actor, Permission.CAMPAIGN_EDIT, payload.campaign_id)
    campaign_service.get_campaign(db, actor.organisation_id, payload.campaign_id)
    version = service.create_form_draft(
        db,
        organisation_id=actor.organisation_id,
        campaign_id=payload.campaign_id,
        actor_id=actor.user_id,
        compensation_enabled=payload.compensation_enabled,
    )
    return FormVersionRead.model_validate(version)


@router.post("/versions/{form_version_id}/approve", response_model=FormVersionRead)
def approve_version(
    form_version_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> FormVersionRead:
    require_permission(actor, Permission.CAMPAIGN_EDIT)
    version = service.approve_form_version(
        db,
        organisation_id=actor.organisation_id,
        form_version_id=form_version_id,
        actor_id=actor.user_id,
    )
    return FormVersionRead.model_validate(version)
