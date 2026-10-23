"""Reporting HTTP router (thin). HR dashboard requires application.review; management
dashboard requires audit.view (read-only, aggregated) in the MVP."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import PermissionDeniedError
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.reporting import service

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


class HRDashboardRead(BaseModel):
    active_campaigns: int
    applications_by_state: dict[str, int]
    open_review_items: int


class ManagementDashboardRead(BaseModel):
    open_campaigns: int
    total_applications: int
    interview_funnel: dict[str, int]
    selected_candidates: str


def _require_any(actor: AuthenticatedActor, *permissions: Permission) -> None:
    if not any(p.value in actor.permissions for p in permissions):
        raise PermissionDeniedError("Insufficient permission to view reports")


@router.get("/hr-dashboard", response_model=HRDashboardRead)
def hr_dashboard(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> HRDashboardRead:
    _require_any(actor, Permission.APPLICATION_REVIEW, Permission.CAMPAIGN_APPROVE)
    data = service.hr_dashboard(db, actor.organisation_id)
    return HRDashboardRead(
        active_campaigns=data.active_campaigns,
        applications_by_state=data.applications_by_state,
        open_review_items=data.open_review_items,
    )


@router.get("/management-dashboard", response_model=ManagementDashboardRead)
def management_dashboard(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ManagementDashboardRead:
    _require_any(actor, Permission.CAMPAIGN_APPROVE, Permission.AUDIT_VIEW)
    data = service.management_dashboard(db, actor.organisation_id)
    return ManagementDashboardRead(
        open_campaigns=data.open_campaigns, total_applications=data.total_applications,
        interview_funnel=data.interview_funnel,
        selected_candidates=data.selected_candidates,
    )
