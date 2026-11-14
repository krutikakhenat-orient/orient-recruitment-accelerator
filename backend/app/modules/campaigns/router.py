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
    CampaignSetupOverviewRead,
    CampaignSetupStatusRead,
    CampaignTransitionRequest,
    ClosureReadinessRead,
    SetupStepRead,
)
from app.modules.campaigns.states import CampaignState
from app.modules.campaigns.transition_service import transition
from app.modules.identity import repository as identity_repo
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import (
    has_permission,
    require_campaign_permission,
    require_permission,
)
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


# Registered before "/{campaign_id}" so the literal path is matched first.
@router.get("/setup-overview", response_model=list[CampaignSetupOverviewRead])
def campaign_setup_overview(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[CampaignSetupOverviewRead]:
    """The setup checklist of every job the caller works on, for the dashboard.

    Same rule as ``/{id}/setup-status``: ``campaign.edit`` or ``campaign.publish``, and only
    jobs the caller is assigned to (object-level). Others get an empty list. Read-only.
    """
    if not (
        has_permission(actor, Permission.CAMPAIGN_EDIT)
        or has_permission(actor, Permission.CAMPAIGN_PUBLISH)
    ):
        return []
    campaigns = repo.list_for_org(db, actor.organisation_id, limit=200, offset=0)
    return [
        CampaignSetupOverviewRead(
            campaign_id=c.id,
            name=c.name,
            position_title=c.position_title,
            state=c.state,
            setup=_setup_read(service.setup_status(db, campaign=c)),
        )
        for c in campaigns
        if c.id in actor.assigned_campaign_ids
    ]


def _setup_read(status: service.SetupStatus) -> CampaignSetupStatusRead:
    return CampaignSetupStatusRead(
        campaign_id=status.campaign_id,
        is_open=status.is_open,
        next_step_key=status.next_step_key,
        steps=[
            SetupStepRead(
                key=s.key, title=s.title, description=s.description,
                status=s.status, who=s.who,
            )
            for s in status.steps
        ],
        latest_jd_version_id=status.latest_jd_version_id,
        latest_jd_status=status.latest_jd_status,
        draft_form_version_id=status.draft_form_version_id,
    )


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


@router.get("/{campaign_id}/closure-readiness", response_model=ClosureReadinessRead)
def campaign_closure_readiness(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ClosureReadinessRead:
    """Advisory pending-work counts to warn HR before completing/cancelling a campaign.

    Read-only; never mutates state and never blocks a transition. Requires the actor to be
    assigned to the campaign (object-level authorisation) and hold ``candidate.view`` — the
    same grant the campaign reports/export use, since the counts summarise this campaign's
    candidates and interviews.
    """
    service.get_campaign(db, actor.organisation_id, campaign_id)  # 404 if missing/other org
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    readiness = service.closure_readiness(
        db, organisation_id=actor.organisation_id, campaign_id=campaign_id
    )
    return ClosureReadinessRead(
        pending_applications=readiness.pending_applications,
        pending_interviews=readiness.pending_interviews,
        has_pending=readiness.has_pending,
    )


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


@router.get("/{campaign_id}/setup-status", response_model=CampaignSetupStatusRead)
def campaign_setup_status(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignSetupStatusRead:
    """The "Set up this job" checklist: which setup steps are done and what is next.

    Read-only. Requires assignment to the campaign and ``campaign.edit`` or
    ``campaign.publish`` (the people who set a job up). Exposes no candidate data.
    """
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)
    needed = (
        Permission.CAMPAIGN_PUBLISH
        if has_permission(actor, Permission.CAMPAIGN_PUBLISH)
        else Permission.CAMPAIGN_EDIT
    )
    require_campaign_permission(actor, needed, campaign_id)
    return _setup_read(service.setup_status(db, campaign=campaign))


@router.post("/{campaign_id}/open-for-applications", response_model=CampaignRead)
def open_for_applications(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignRead:
    """Open a fully set-up job for applications (requires ``campaign.publish`` + assignment).

    Fails with a plain message naming the missing checklist step. Every internal state hop
    runs through the TransitionService and is audited; attaching the default privacy notice
    is audited too.
    """
    campaign = service.get_campaign(db, actor.organisation_id, campaign_id)
    updated = service.open_for_applications(db, actor=actor, campaign=campaign)
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
