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


def list_assessable(
    db: Session, organisation_id: uuid.UUID, interviewer_id: uuid.UUID
) -> list[Application]:
    """Applications awaiting a panel assessment: those CHECKED_IN (new flow) or, for
    historical records, ATTENDED (legacy flow).

    Scoped to the interviewer's ACTIVE assignments (by campaign UUID), so a panel member
    only ever sees candidates for campaigns they are assigned to. No assignment => empty.
    Exposes no screening internals.
    """
    from sqlalchemy import select

    from app.modules.interviews import assignment_service

    assigned_campaign_ids = assignment_service.interviewer_assigned_campaign_ids(
        db, organisation_id=organisation_id, interviewer_id=interviewer_id
    )
    if not assigned_campaign_ids:
        return []

    stmt = (
        select(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.campaign_id.in_(assigned_campaign_ids),
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


def panel_worklist(
    db: Session,
    organisation_id: uuid.UUID,
    interviewer_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """The Interview Panel's worklist for ONE interviewer: active interviews for the
    campaigns (and stages) this user is actively assigned to.

    Isolation (security): the worklist is scoped to the authenticated interviewer's ACTIVE
    ``InterviewAssignment`` rows, by stable campaign UUID — never by campaign display name.
    An interviewer with no active assignments gets an EMPTY worklist. When ``campaign_id`` is
    supplied (the UI opening one job bucket), it is intersected with the assigned set and
    ignored if not assigned, so a client cannot widen its own view. Stage-scoped assignments
    restrict the rows to invitations for that stage (whole-campaign assignments cover any
    stage). Removing an assignment revokes access on the next call (active rows are re-read).

    Minimal fields only (candidate name) — no screening data.
    """
    from sqlalchemy import select

    from app.modules.interviews import assignment_service
    from app.modules.interviews.models import InterviewInvitation

    assignments = assignment_service.active_assignments_for_interviewer(
        db, organisation_id=organisation_id, interviewer_id=interviewer_id
    )
    assigned_campaign_ids = {asg.campaign_id for asg in assignments}
    if not assigned_campaign_ids:
        return []

    # If the UI asked for a specific campaign bucket, it must be one the interviewer is
    # assigned to; otherwise return nothing (never fall back to a broader view).
    if campaign_id is not None:
        if campaign_id not in assigned_campaign_ids:
            return []
        target_campaign_ids = {campaign_id}
    else:
        target_campaign_ids = assigned_campaign_ids

    # Per-campaign stage restriction: if the interviewer only has stage-scoped assignments
    # for a campaign (no whole-campaign row), restrict that campaign's rows to those stages.
    whole_campaign: set[uuid.UUID] = {
        asg.campaign_id for asg in assignments if asg.stage_id is None
    }
    stage_scope: dict[uuid.UUID, set[uuid.UUID]] = {}
    for asg in assignments:
        if asg.stage_id is not None:
            stage_scope.setdefault(asg.campaign_id, set()).add(asg.stage_id)

    states = tuple(_PANEL_STATE_STAGE)
    apps = list(
        db.execute(
            select(Application)
            .where(
                Application.organisation_id == organisation_id,
                Application.state.in_(states),
                Application.campaign_id.in_(target_campaign_ids),
            )
            .order_by(Application.created_at.desc())
        ).scalars()
    )
    # Map application_id -> most recent invitation (id + its stage) for the check-in/out
    # actions and for stage-scoped assignment filtering.
    inv_by_app: dict[uuid.UUID, uuid.UUID] = {}
    inv_stage_by_app: dict[uuid.UUID, uuid.UUID | None] = {}
    for inv in db.execute(
        select(InterviewInvitation)
        .where(InterviewInvitation.organisation_id == organisation_id)
        .order_by(InterviewInvitation.created_at.desc())
    ).scalars():
        if inv.application_id not in inv_by_app:
            inv_by_app[inv.application_id] = inv.id
            inv_stage_by_app[inv.application_id] = inv.stage_id

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

    # Resolve a readable role/campaign label per application so the panel UI can GROUP
    # candidates by the role they are interviewing for. The authoritative grouping key is the
    # stable campaign_id (UUID); campaign_name is a display label only.
    from app.modules.campaigns.models import Campaign

    campaign_ids = {a.campaign_id for a in apps}
    campaign_name: dict[uuid.UUID, str] = {}
    for cid in campaign_ids:
        camp = db.get(Campaign, cid)
        if camp is not None:
            campaign_name[cid] = camp.position_title or camp.name or str(cid)

    out: list[dict[str, Any]] = []
    for a in apps:
        # Stage-scope enforcement: for a campaign where the interviewer has ONLY stage-scoped
        # assignments (no whole-campaign row), include an application only if its current
        # invitation's stage is one of the assigned stages. A NULL invitation stage is not
        # covered by a stage-scoped assignment.
        if a.campaign_id not in whole_campaign:
            allowed_stages = stage_scope.get(a.campaign_id, set())
            inv_stage = inv_stage_by_app.get(a.id)
            if inv_stage is None or inv_stage not in allowed_stages:
                continue
        name = a.answers.get("full_name") if isinstance(a.answers, dict) else None
        out.append(
            {
                "application_id": a.id,
                "campaign_id": a.campaign_id,
                "campaign_name": campaign_name.get(a.campaign_id, str(a.campaign_id)),
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
    db: Session,
    *,
    organisation_id: uuid.UUID,
    interviewer_id: uuid.UUID,
    application: Application,
) -> bool:
    """True if THIS interview-panel member may read this candidate's interview context
    (resume / application / extracted fields).

    Two conditions must BOTH hold:
      1. the application is currently in the interview lifecycle (scheduled .. checked-out),
         so panel access never reaches candidates still in screening/review; and
      2. the panel member has an ACTIVE interviewer assignment covering the application's
         campaign (whole-campaign, or the specific stage of the candidate's current
         invitation). This is the object-level isolation that stops one interviewer from
         reading candidates for a campaign/stage they are not assigned to — it cannot be
         bypassed by supplying another application's id, because the assignment is checked
         against the authenticated interviewer for the loaded application's campaign.

    Exposes no screening internals — only the interview-context documents the panel needs.
    """
    from app.modules.interviews import assignment_service
    from app.modules.interviews.models import InterviewInvitation

    if (
        application.organisation_id != organisation_id
        or application.state not in PANEL_INTERVIEW_STATES
    ):
        return False

    # The stage of the candidate's current (most recent) invitation, for stage-scoped checks.
    from sqlalchemy import select

    invitation = db.execute(
        select(InterviewInvitation)
        .where(
            InterviewInvitation.organisation_id == organisation_id,
            InterviewInvitation.application_id == application.id,
        )
        .order_by(InterviewInvitation.created_at.desc())
    ).scalars().first()
    stage_id = invitation.stage_id if invitation is not None else None

    return assignment_service.is_interviewer_assigned_to_campaign_stage(
        db,
        organisation_id=organisation_id,
        interviewer_id=interviewer_id,
        campaign_id=application.campaign_id,
        stage_id=stage_id,
    )


def require_panel_assignment(
    db: Session, *, actor: AuthenticatedActor, application: Application
) -> None:
    """Enforce that the authenticated panel member is assigned to this candidate's
    campaign/stage before an interview-day action (assess / check-in / check-out /
    attendance). Raises PermissionDeniedError otherwise.

    This checks ASSIGNMENT only (campaign, and stage of the candidate's current invitation);
    it deliberately does NOT also require the application to be in an interview-lifecycle
    state — each action enforces its own state precondition (e.g. "must be checked in") and
    returns the appropriate ConflictError. Checking assignment first means a forged/unassigned
    application id is refused (403) without leaking the candidate's state, while an assigned
    interviewer acting at the wrong moment still gets the clear state error. Applied in the
    service layer (not just the router), so it holds regardless of the endpoint or the
    application id the client supplies.
    """
    from app.core.errors import PermissionDeniedError
    from app.modules.interviews import assignment_service
    from app.modules.interviews.models import InterviewInvitation

    if application.organisation_id != actor.organisation_id:
        raise PermissionDeniedError(
            "You are not assigned to interview candidates for this campaign/stage"
        )

    from sqlalchemy import select

    invitation = db.execute(
        select(InterviewInvitation)
        .where(
            InterviewInvitation.organisation_id == application.organisation_id,
            InterviewInvitation.application_id == application.id,
        )
        .order_by(InterviewInvitation.created_at.desc())
    ).scalars().first()
    stage_id = invitation.stage_id if invitation is not None else None

    if not assignment_service.is_interviewer_assigned_to_campaign_stage(
        db,
        organisation_id=application.organisation_id,
        interviewer_id=actor.user_id,
        campaign_id=application.campaign_id,
        stage_id=stage_id,
    ):
        raise PermissionDeniedError(
            "You are not assigned to interview candidates for this campaign/stage"
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
    # Object-level interviewer isolation FIRST: the panel member must hold an ACTIVE
    # assignment covering this candidate's campaign/stage. Checking this before anything
    # else means a forged/unassigned application id is refused (403) without leaking the
    # candidate's state — it cannot be bypassed by posting another campaign's application id.
    require_panel_assignment(db, actor=actor, application=application)
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
