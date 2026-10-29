"""Reporting HTTP router (thin). HR dashboard requires application.review; management
dashboard requires audit.view (read-only, aggregated) in the MVP."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import PermissionDeniedError
from app.db.session import get_db
from app.modules.campaigns import service as campaign_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import has_permission, require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.reporting import export_service, report_builder, service

_XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

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


class ReportColumnRead(BaseModel):
    key: str
    label: str
    width: int


class CandidateReportRowRead(BaseModel):
    application_id: str
    candidate_name: str
    email: str | None
    phone: str | None
    contact_masked: bool
    applied_position: str
    status: str
    status_label: str
    scored: bool
    overall_score: float | None
    jd_skills_match: float | None
    recommendation: str | None
    manual_review_required: bool
    conflict_flagged: bool
    relevant_skills: list[str]
    key_strengths: list[str]
    missing_requirements: list[str]
    unverified_requirements: list[str]
    experience_summary: str | None
    education_summary: str | None
    resume_available: bool
    resume_filename: str | None
    rank: int | None


class CampaignReportSummaryRead(BaseModel):
    campaign_id: str
    campaign_name: str
    position_title: str
    jd_role: str | None
    status: str
    status_label: str
    number_of_openings: int
    total_candidates: int
    scored_candidates: int
    unscored_candidates: int
    contact_unmasked: bool
    generated_at: str
    score_note: str


class CampaignReportRead(BaseModel):
    """The in-app report preview payload. Built from the SAME shared report the Excel export
    renders, so the preview table and the downloaded workbook show identical records."""

    summary: CampaignReportSummaryRead
    columns: list[ReportColumnRead]
    rows: list[CandidateReportRowRead]


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


@router.get("/campaigns/{campaign_id}/report", response_model=CampaignReportRead)
def campaign_report(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignReportRead:
    """The in-app report preview for a campaign, as JSON.

    Built from the SAME shared report the Excel export renders, so the preview table and the
    downloaded workbook show identical candidate records. Read-only: reuses the saved
    screening ranking; nothing is re-scored. Requires candidate.view AND assignment to the
    campaign. Email/phone are unmasked ONLY when the actor holds candidate.view_pii (each
    reveal is audited); otherwise they are masked.
    """
    campaign = campaign_service.get_campaign(db, actor.organisation_id, campaign_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    unmask = has_permission(actor, Permission.CANDIDATE_VIEW_PII)
    report = report_builder.build_campaign_report(
        db,
        organisation_id=actor.organisation_id,
        campaign=campaign,
        actor_id=actor.user_id,
        unmask_contact=unmask,
    )
    # dataclasses -> pydantic (field names match 1:1).
    return CampaignReportRead(
        summary=CampaignReportSummaryRead(**vars(report.summary)),
        columns=[ReportColumnRead(**vars(c)) for c in report.columns],
        rows=[CandidateReportRowRead(**vars(r)) for r in report.rows],
    )


@router.get("/campaigns/{campaign_id}/export")
def export_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> Response:
    """Export one campaign's candidates to an HR-focused .xlsx workbook.

    Read-only: scores/ranks come from the already-saved screening runs (the same selection
    the UI and the in-app preview use); no scoring is re-run and no records are mutated.
    Requires candidate.view AND assignment to the campaign (object-level authorisation).
    Candidate email/phone are unmasked ONLY when the actor holds candidate.view_pii (each
    reveal audited); otherwise masked. Built from the SAME shared report as the preview.
    """
    # 404 if the campaign does not exist or belongs to another organisation.
    campaign = campaign_service.get_campaign(db, actor.organisation_id, campaign_id)
    # Object-level authorisation: hold candidate.view AND be assigned to this campaign.
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    unmask = has_permission(actor, Permission.CANDIDATE_VIEW_PII)

    workbook_bytes = export_service.build_campaign_workbook_bytes(
        db,
        organisation_id=actor.organisation_id,
        campaign=campaign,
        actor_id=actor.user_id,
        unmask_contact=unmask,
    )
    # Safe, generated filename (no user-controlled text in the header).
    filename = f"campaign-{campaign.id}-report.xlsx"
    return Response(
        content=workbook_bytes,
        media_type=_XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
