"""Campaign HTTP router (thin). State changes go through the TransitionService."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, requires
from app.core.errors import ValidationError
from app.db.session import get_db
from app.modules.campaigns import repository as repo
from app.modules.campaigns import service
from app.modules.campaigns.schemas import (
    CampaignAssignRequest,
    CampaignCreate,
    CampaignRead,
    CampaignTransitionRequest,
)
from app.modules.campaigns.states import CampaignState
from app.modules.campaigns.transition_service import transition
from app.modules.identity import repository as identity_repo
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


@router.post("", response_model=CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.CAMPAIGN_CREATE)),
) -> CampaignRead:
    campaign = service.create_campaign(db, actor.organisation_id, payload, actor.user_id)
    return CampaignRead.model_validate(campaign)


@router.get("", response_model=list[CampaignRead])
def list_campaigns(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CampaignRead]:
    campaigns = repo.list_for_org(db, actor.organisation_id, limit=limit, offset=offset)
    return [CampaignRead.model_validate(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignRead:
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)
    return CampaignRead.model_validate(campaign)


@router.delete("/{campaign_id}", status_code=200)
def delete_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> dict[str, int | str]:
    """Hard-delete a campaign and all records scoped to it (applications, screening/review
    history, JD/rules/threshold/form config, assignments).

    Destructive and consequential: requires campaign.edit AND assignment to this campaign
    (object-level authorisation). Every deletion is audited with the application count. The
    UI requires a typed confirmation before calling this.
    """
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)
    require_campaign_permission(actor, Permission.CAMPAIGN_EDIT, campaign_id)
    deleted = service.delete_campaign(
        db, organisation_id=actor.organisation_id, campaign=campaign, actor_id=actor.user_id
    )
    db.commit()
    return {"deleted_campaign_id": str(campaign_id), "applications_removed": deleted}


@router.post("/{campaign_id}/rescore", status_code=200)
def rescore_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> dict[str, int | str]:
    """Regenerate the campaign's JD-derived scoring criteria and re-screen every applicant.

    Safe remediation for candidates showing 0/100 because the campaign's approved rule-set
    predates JD-based skill criteria. Requires campaign.edit + assignment. Reuses existing
    candidate/application/resume records; creates new immutable screening runs (prior runs
    retained). Nothing is reset or deleted.
    """
    from app.modules.screening import service as screening_service

    service.get_campaign(db, actor.organisation_id, campaign_id)  # 404 if missing/other org
    require_campaign_permission(actor, Permission.CAMPAIGN_EDIT, campaign_id)
    summary = screening_service.rescore_campaign(
        db, organisation_id=actor.organisation_id, campaign_id=campaign_id, actor=actor
    )
    db.commit()
    return {
        "campaign_id": str(campaign_id),
        "applications_rescored": summary.rescored,
        "criteria_count": summary.criteria_count,
    }


@router.post("/{campaign_id}/transition", response_model=CampaignRead)
def transition_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignTransitionRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignRead:
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)
    try:
        destination = CampaignState(payload.destination)
    except ValueError as exc:
        raise ValidationError(f"Unknown campaign state: {payload.destination}") from exc
    updated = transition(
        db, actor=actor, campaign=campaign, destination=destination, reason=payload.reason
    )
    return CampaignRead.model_validate(updated)


@router.post("/{campaign_id}/fast-track-open", response_model=CampaignRead)
def fast_track_open(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignRead:
    """Drive a campaign whose five artifacts are already approved straight to
    APPLICATIONS_OPEN in one action. Not a bypass — every transition is still permission
    checked and audited; it only collapses the final approval gates."""
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)
    updated = service.fast_track_open(db, actor=actor, campaign=campaign)
    return CampaignRead.model_validate(updated)


@router.post("/{campaign_id}/assignments", response_model=CampaignRead, status_code=201)
def assign_to_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignAssignRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignRead:
    """Assign a staff user to a campaign (object-level authorisation).

    Assigning another user requires the ``campaign.edit`` permission. Self-assignment
    (no email provided) is allowed for any authenticated staff member so they can pick up
    work on a campaign; the normal per-action permission checks still apply afterwards.
    """
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)

    if payload.email:
        require_permission(actor, Permission.CAMPAIGN_EDIT)
        target = identity_repo.get_user_by_email(db, actor.organisation_id, payload.email)
        if target is None:
            raise ValidationError("No staff user with that email in this organisation")
        target_user_id = target.id
    else:
        target_user_id = actor.user_id

    service.assign_user(
        db,
        organisation_id=actor.organisation_id,
        campaign=campaign,
        user_id=target_user_id,
        actor_id=actor.user_id,
    )
    db.commit()
    db.refresh(campaign)
    return CampaignRead.model_validate(campaign)
