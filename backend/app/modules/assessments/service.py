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
    """Applications awaiting a panel assessment: those CHECKED_IN (new flow) or, for
    historical records, ATTENDED (legacy flow).

    Panel members hold only ``assessment.submit`` (no candidate.view), so this is the one
    minimal view they get — enough to find the candidate they interviewed and record a
    verdict. It deliberately exposes no screening internals.
    """
    from sqlalchemy import select

    stmt = (
        select(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.state.in_(
                (
                    ApplicationState.CHECKED_IN.value,
                    ApplicationState.ATTENDED.value,
                )
            ),
        )
        .order_by(Application.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


def get_assessment(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    application_id: uuid.UUID,
    panel_member_id: uuid.UUID | None = None,
) -> Assessment | None:
    """The saved assessment for an application, optionally scoped to one panel member.

    Used to (a) prevent duplicate submissions and (b) let the Assessment tab rehydrate a
    previously-saved assessment so values survive tab switches / refreshes. When
    ``panel_member_id`` is given, returns only that assessor's assessment; otherwise the
    most recent assessment for the application.
    """
    from sqlalchemy import select

    stmt = select(Assessment).where(
        Assessment.organisation_id == organisation_id,
        Assessment.application_id == application_id,
    )
    if panel_member_id is not None:
        stmt = stmt.where(Assessment.panel_member_id == panel_member_id)
    stmt = stmt.order_by(Assessment.created_at.desc())
    return db.execute(stmt).scalars().first()


# States that make up a panel member's worklist, and the UI stage each maps to. The new
# interview-day lifecycle is Scheduled -> Checked In -> Assessed -> Checked Out, so the UI
# stages are: confirm arrival (to_check_in), assess (to_assess), check out (to_check_out),
# done (completed). Legacy ATTENDED rows map to to_assess so they can still be assessed.
_PANEL_STATE_STAGE: dict[str, str] = {
    ApplicationState.INTERVIEW_SCHEDULED.value: "to_check_in",
    ApplicationState.CHECKED_IN.value: "to_assess",
    ApplicationState.ATTENDED.value: "to_assess",
    ApplicationState.ASSESSED.value: "to_check_out",
    ApplicationState.CHECKED_OUT.value: "completed",
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
    # Map application_id -> most recent invitation id (for the check-in/out actions).
    inv_by_app: dict[uuid.UUID, uuid.UUID] = {}
    for inv in db.execute(
        select(InterviewInvitation)
        .where(InterviewInvitation.organisation_id == organisation_id)
        .order_by(InterviewInvitation.created_at.desc())
    ).scalars():
        inv_by_app.setdefault(inv.application_id, inv.id)

    # Which of these applications already have an assessment (so the UI can show status and
    # gate check-out). One query, then a set lookup — no per-row database call.
    app_ids = [a.id for a in apps]
    assessed_app_ids: set[uuid.UUID] = set()
    if app_ids:
        assessed_app_ids = set(
            db.execute(
                select(Assessment.application_id).where(
                    Assessment.organisation_id == organisation_id,
                    Assessment.application_id.in_(app_ids),
                )
            ).scalars()
        )

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
                "has_assessment": a.id in assessed_app_ids,
            }
        )
    return out


# Application states in which a candidate is actively on a panel member's interview
# worklist. A panel member (assessment.submit) may read JUST this candidate's resume,
# application and extracted fields while the candidate is in one of these states — the
# minimal context needed to conduct and record the interview. Outside these states (e.g. a
# candidate still in screening, or long after the interview) a panel member has no access.
PANEL_INTERVIEW_STATES: frozenset[str] = frozenset(_PANEL_STATE_STAGE)


def panel_member_may_view_candidate(
    db: Session, *, organisation_id: uuid.UUID, application: Application
) -> bool:
    """True if an interview-panel member is allowed to read this candidate's interview
    context (resume / application / extracted fields).

    Access is scoped by APPLICATION STATE, not campaign assignment: panel members are
    invited to interview specific candidates rather than assigned as campaign authors, so
    the authoritative signal is that the application is currently in the interview lifecycle
    (scheduled through checked-out). This deliberately grants NO access to candidates still
    in screening/review, and exposes no screening internals — only the interview-context
    documents the panel needs. Object-level safety is preserved: the caller has already
    loaded THIS application, and only this candidate's data is returned.
    """
    return (
        application.organisation_id == organisation_id
        and application.state in PANEL_INTERVIEW_STATES
    )


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
    # An assessment can be submitted once the candidate has been checked in (new flow) or,
    # for legacy records, marked attended. This guards against assessing someone who merely
    # had an interview scheduled but never arrived/checked in.
    if application.state not in {
        ApplicationState.CHECKED_IN.value,
        ApplicationState.ATTENDED.value,
    }:
        raise ConflictError(
            "An assessment can only be submitted after the candidate has been checked in"
        )
    # Prevent DUPLICATE assessment submissions by the same panel member for the same
    # application. Reassessment is not part of the current workflow, so a second submission
    # from the same assessor is rejected rather than silently creating a duplicate record.
    if get_assessment(db, organisation_id=application.organisation_id,
                       application_id=application.id, panel_member_id=actor.user_id) is not None:
        raise ConflictError("You have already submitted an assessment for this candidate")
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
