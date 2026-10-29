"""Assessment HTTP router (thin). Requires assessment.submit + campaign authz."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.assessments import service
from app.modules.assessments.schemas import (
    AssessableApplicationRead,
    AssessmentDetailRead,
    AssessmentRead,
    AssessmentSubmit,
    PanelDashboardRead,
    PanelInterviewRead,
)
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import has_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/assessments", tags=["assessments"])


@router.get("/assignable", response_model=list[AssessableApplicationRead])
def list_assignable(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[AssessableApplicationRead]:
    """Candidates who attended an interview and await this panel member's assessment.
    Requires assessment.submit. Returns only the candidate's name — no screening data."""
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    apps = service.list_assessable(db, actor.organisation_id, actor.user_id)
    out: list[AssessableApplicationRead] = []
    for a in apps:
        name = a.answers.get("full_name") if isinstance(a.answers, dict) else None
        out.append(
            AssessableApplicationRead(
                application_id=a.id,
                campaign_id=a.campaign_id,
                candidate_name=str(name) if name else "Candidate",
            )
        )
    return out


@router.get("/panel", response_model=PanelDashboardRead)
def panel_dashboard(
    campaign_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PanelDashboardRead:
    """The Interview Panel's own dashboard: interviews to attend / to assess / completed,
    with counts. Requires assessment.submit. Exposes only candidate names, no screening
    data.

    Strictly scoped to the authenticated interviewer's ACTIVE assignments (by campaign
    UUID). An optional ``campaign_id`` narrows to one assigned job bucket; a campaign the
    interviewer is not assigned to yields an empty worklist. No assignment => empty."""
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    rows = service.panel_worklist(
        db, actor.organisation_id, actor.user_id, campaign_id=campaign_id
    )
    interviews = [PanelInterviewRead(**r) for r in rows]
    counts = {"to_check_in": 0, "to_assess": 0, "to_check_out": 0, "completed": 0}
    for r in rows:
        counts[r["stage"]] += 1
    return PanelDashboardRead(
        to_check_in=counts["to_check_in"],
        to_assess=counts["to_assess"],
        to_check_out=counts["to_check_out"],
        completed=counts["completed"],
        total=len(rows),
        interviews=interviews,
    )


@router.get("/by-application/{application_id}", response_model=AssessmentDetailRead | None)
def get_assessment_for_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AssessmentDetailRead | None:
    """The saved assessment for an application, so the Assessment tab can rehydrate values
    (surviving tab switches / refreshes) and Recruiter Admin can review the verdict.

    A panel member (assessment.submit) sees only their OWN assessment for the candidate;
    staff who can view candidates (candidate.view) see the assessment for review. Returns
    null when no assessment has been saved yet. No screening internals are exposed.
    """
    can_view_candidates = has_permission(actor, Permission.CANDIDATE_VIEW)
    can_submit = has_permission(actor, Permission.ASSESSMENT_SUBMIT)
    panel_member_id: uuid.UUID | None = None
    if can_submit and not can_view_candidates:
        # Pure panel member: scope strictly to their own assessment.
        panel_member_id = actor.user_id
    elif not can_view_candidates:
        # Neither panel nor candidate-viewer: not allowed.
        require_permission(actor, Permission.CANDIDATE_VIEW)
    assessment = service.get_assessment(
        db,
        organisation_id=actor.organisation_id,
        application_id=application_id,
        panel_member_id=panel_member_id,
    )
    if assessment is None:
        return None
    return AssessmentDetailRead.model_validate(assessment)


@router.post("", response_model=AssessmentRead, status_code=201)
def submit_assessment(
    payload: AssessmentSubmit,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AssessmentRead:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    # Panel members hold the global assessment.submit permission (they are invited to
    # interview specific candidates, not assigned as campaign authors). The ATTENDED-state
    # guard in the service ensures only genuinely-interviewed candidates can be assessed.
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    assessment = service.submit_assessment(
        db, actor=actor, application=application, criteria_scores=payload.criteria_scores,
        recommendation=payload.recommendation,
        problem_solving_notes=payload.problem_solving_notes,
        role_understanding_notes=payload.role_understanding_notes,
        interview_notes=payload.interview_notes,
        conflict_declared=payload.conflict_declared, conflict_detail=payload.conflict_detail,
    )
    return AssessmentRead.model_validate(assessment)
