"""Assessment HTTP router (thin). Requires assessment.submit + campaign authz."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.assessments import service
from app.modules.assessments.schemas import (
    AssessableApplicationRead,
    AssessmentRead,
    AssessmentSubmit,
    PanelDashboardRead,
    PanelInterviewRead,
)
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_permission
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
    apps = service.list_assessable(db, actor.organisation_id)
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
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PanelDashboardRead:
    """The Interview Panel's own dashboard: interviews to attend / to assess / completed,
    with counts. Requires assessment.submit. Exposes only candidate names, no screening
    data."""
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    rows = service.panel_worklist(db, actor.organisation_id)
    interviews = [PanelInterviewRead(**r) for r in rows]
    counts = {"to_attend": 0, "to_assess": 0, "completed": 0}
    for r in rows:
        counts[r["stage"]] += 1
    return PanelDashboardRead(
        to_attend=counts["to_attend"],
        to_assess=counts["to_assess"],
        completed=counts["completed"],
        total=len(rows),
        interviews=interviews,
    )


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
