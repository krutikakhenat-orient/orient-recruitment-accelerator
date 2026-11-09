"""SLA HTTP router (thin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_access, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.sla import service
from app.modules.sla.schemas import (
    SlaItemRead,
    SlaPolicyRead,
    SlaPolicyUpdate,
    SlaRunResult,
    SlaSummaryRead,
)

router = APIRouter(prefix="/api/v1/sla", tags=["sla"])


def _scope(actor: AuthenticatedActor, campaign_id: uuid.UUID | None) -> set[uuid.UUID]:
    if campaign_id is not None:
        require_campaign_access(actor, campaign_id)
        return {campaign_id}
    return set(actor.assigned_campaign_ids)


@router.get("/policy", response_model=SlaPolicyRead)
def get_policy(
    campaign_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> SlaPolicyRead:
    require_permission(actor, Permission.CANDIDATE_VIEW)
    return service.effective_policy(db, actor.organisation_id, campaign_id)


@router.put("/policy", response_model=SlaPolicyRead)
def put_policy(
    payload: SlaPolicyUpdate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> SlaPolicyRead:
    """Change the shortlisting target. Needs campaign.approve (HR sign-off)."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    if payload.campaign_id is not None:
        require_campaign_access(actor, payload.campaign_id)
    return service.save_policy(
        db, actor=actor, campaign_id=payload.campaign_id, window_hours=payload.window_hours,
        at_risk_percent=payload.at_risk_percent,
    )


@router.get("/summary", response_model=SlaSummaryRead)
def get_summary(
    campaign_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> SlaSummaryRead:
    require_permission(actor, Permission.CANDIDATE_VIEW)
    return service.summary(db, actor.organisation_id, _scope(actor, campaign_id), campaign_id)


@router.get("/applications", response_model=list[SlaItemRead])
def list_items(
    campaign_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(on_track|at_risk|overdue|paused)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[SlaItemRead]:
    """Open applications with their status, most urgent first."""
    require_permission(actor, Permission.CANDIDATE_VIEW)
    items, _ = service.evaluate(db, actor.organisation_id, _scope(actor, campaign_id))
    rows = [service.to_item(ev) for ev in items if status is None or ev.status == status]
    rows.sort(key=lambda r: r.hours_remaining)
    return rows[:200]


@router.post("/run-check", response_model=SlaRunResult)
def run_check(
    campaign_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> SlaRunResult:
    """Record reminders / overdue notices now (an automatic scheduler is not connected yet)."""
    require_permission(actor, Permission.APPLICATION_REVIEW)
    return service.run_check(
        db, settings=settings, actor=actor, campaign_ids=_scope(actor, campaign_id)
    )
