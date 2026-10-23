"""Assessment service (Req 10.3). Submitting an assessment moves an ATTENDED application
to ASSESSED via the transition service. If a conflict is declared, detail is required."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.applications.transition_service import transition
from app.modules.assessments.models import Assessment, AssessmentRecommendation
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.schemas import AuthenticatedActor


def list_assessable(db: Session, organisation_id: uuid.UUID) -> list[Application]:
    """Applications that have ATTENDED an interview and are awaiting a panel assessment.

    Panel members hold only ``assessment.submit`` (no candidate.view), so this is the one
    minimal view they get — enough to find the candidate they interviewed and record a
    verdict. It deliberately exposes no screening internals.
    """
    from sqlalchemy import select

    stmt = (
        select(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.state == ApplicationState.ATTENDED.value,
        )
        .order_by(Application.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


# States that make up a panel member's worklist, and the UI stage each maps to.
_PANEL_STATE_STAGE: dict[str, str] = {
    ApplicationState.INTERVIEW_SCHEDULED.value: "to_attend",
    ApplicationState.ATTENDED.value: "to_assess",
    ApplicationState.ASSESSED.value: "completed",
}


def panel_worklist(db: Session, organisation_id: uuid.UUID) -> list[dict[str, Any]]:
    """The Interview Panel's worklist: candidates who are scheduled (to confirm attendance),
    attended (to assess), or already assessed (completed), each with its invitation id so the
    panel can record attendance. Minimal fields only (candidate name) — no screening data.

    Deterministic ordering (newest application first). Scoped to the organisation; panel
    members are invited to specific candidates rather than campaign-assigned, so the
    worklist is the whole org's active interviews — the state guard keeps actions correct.
    """
    from sqlalchemy import select

    from app.modules.interviews.models import InterviewInvitation

    states = tuple(_PANEL_STATE_STAGE)
    apps = list(
        db.execute(
            select(Application)
            .where(
                Application.organisation_id == organisation_id,
                Application.state.in_(states),
            )
            .order_by(Application.created_at.desc())
        ).scalars()
    )
    # Map application_id -> most recent invitation id (for the attendance action).
    inv_by_app: dict[uuid.UUID, uuid.UUID] = {}
    for inv in db.execute(
        select(InterviewInvitation)
        .where(InterviewInvitation.organisation_id == organisation_id)
        .order_by(InterviewInvitation.created_at.desc())
    ).scalars():
        inv_by_app.setdefault(inv.application_id, inv.id)

    out: list[dict[str, Any]] = []
    for a in apps:
        name = a.answers.get("full_name") if isinstance(a.answers, dict) else None
        out.append(
            {
                "application_id": a.id,
                "campaign_id": a.campaign_id,
                "invitation_id": inv_by_app.get(a.id),
                "candidate_name": str(name) if name else "Candidate",
                "state": a.state,
                "stage": _PANEL_STATE_STAGE[a.state],
            }
        )
    return out


def submit_assessment(
    db: Session,
    *,
    actor: AuthenticatedActor,
    application: Application,
    criteria_scores: dict[str, Any],
    recommendation: AssessmentRecommendation,
    problem_solving_notes: str | None = None,
    role_understanding_notes: str | None = None,
    interview_notes: str | None = None,
    conflict_declared: bool = False,
    conflict_detail: str | None = None,
) -> Assessment:
    if application.state != ApplicationState.ATTENDED.value:
        raise ConflictError("An assessment can only be submitted for an attended interview")
    if conflict_declared and not (conflict_detail and conflict_detail.strip()):
        raise ValidationError("A conflict detail is required when a conflict is declared")

    assessment = Assessment(
        organisation_id=application.organisation_id,
        application_id=application.id,
        campaign_id=application.campaign_id,
        panel_member_id=actor.user_id,
        criteria_scores=criteria_scores,
        problem_solving_notes=problem_solving_notes,
        role_understanding_notes=role_understanding_notes,
        interview_notes=interview_notes,
        recommendation=recommendation.value,
        conflict_declared=conflict_declared,
        conflict_detail=conflict_detail,
        created_by=actor.user_id,
    )
    db.add(assessment)
    db.flush()

    transition(db, application=application, destination=ApplicationState.ASSESSED,
               reason="assessment submitted", actor=actor)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id, actor_id=actor.user_id,
            action="assessment.submitted", entity_type="assessment",
            entity_id=str(assessment.id), new_state_ref=recommendation.value,
        ),
    )
    return assessment
