"""Interview workflow service (Req 10.1, 10.2; AC-14).

Issuing an invitation requires an authorised approver (interview.approve, enforced at the
router) and moves the application INTERVIEW_RECOMMENDED -> INTERVIEW_SCHEDULED only when a
slot is assigned. Candidates are never auto-invited: an invitation exists only because an
authorised actor created it. Slot capacity is enforced on confirmation.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.applications.transition_service import transition
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews.models import (
    AttendanceStatus,
    InterviewInvitation,
    InterviewSlot,
    InterviewStage,
    InvitationStatus,
)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def list_stages(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[InterviewStage]:
    from sqlalchemy import select

    stmt = (
        select(InterviewStage)
        .where(
            InterviewStage.organisation_id == organisation_id,
            InterviewStage.campaign_id == campaign_id,
        )
        .order_by(InterviewStage.sequence)
    )
    return list(db.execute(stmt).scalars())


def list_slots(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[InterviewSlot]:
    """All slots across the campaign's stages, soonest first."""
    from sqlalchemy import select

    stage_ids = [s.id for s in list_stages(db, organisation_id, campaign_id)]
    if not stage_ids:
        return []
    stmt = (
        select(InterviewSlot)
        .where(
            InterviewSlot.organisation_id == organisation_id,
            InterviewSlot.stage_id.in_(stage_ids),
        )
        .order_by(InterviewSlot.slot_date, InterviewSlot.start_time)
    )
    return list(db.execute(stmt).scalars())


def list_invitations(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[InterviewInvitation]:
    from sqlalchemy import select

    stmt = (
        select(InterviewInvitation)
        .where(
            InterviewInvitation.organisation_id == organisation_id,
            InterviewInvitation.campaign_id == campaign_id,
        )
        .order_by(InterviewInvitation.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


def create_stage(
    db: Session, *, organisation_id: uuid.UUID, campaign_id: uuid.UUID,
    name: str, sequence: int, actor_id: uuid.UUID,
) -> InterviewStage:
    stage = InterviewStage(
        organisation_id=organisation_id, campaign_id=campaign_id, name=name,
        sequence=sequence, created_by=actor_id,
    )
    db.add(stage)
    db.flush()
    return stage


def create_slot(
    db: Session, *, organisation_id: uuid.UUID, stage_id: uuid.UUID,
    slot_date: dt.date, start_time: str, location: str | None, mode: str,
    capacity: int, actor_id: uuid.UUID,
) -> InterviewSlot:
    stage = db.get(InterviewStage, stage_id)
    if stage is None or stage.organisation_id != organisation_id:
        raise NotFoundError("Interview stage not found")
    if capacity < 1:
        raise ValidationError("Slot capacity must be at least 1")
    slot = InterviewSlot(
        stage_id=stage_id, organisation_id=organisation_id, slot_date=slot_date,
        start_time=start_time, location=location, mode=mode, capacity=capacity,
        created_by=actor_id,
    )
    db.add(slot)
    db.flush()
    return slot


def approve_invitation(
    db: Session, *, actor: AuthenticatedActor, application: Application,
    stage_id: uuid.UUID | None = None, reason: str | None = None,
) -> InterviewInvitation:
    """Issue an authorised interview invitation (AC-14). The application must be in a
    state from which an interview can be recommended.

    ``reason`` is an optional free-text justification. It is REQUIRED (enforced at the
    router / service caller) when an authorised actor overrides screening to select a
    below-threshold candidate from the Review Queue, so every such override is auditable
    with its rationale (security.md: override actions require permission AND reason)."""
    if application.state not in {
        ApplicationState.SCREENED.value, ApplicationState.MANUAL_REVIEW.value,
    }:
        raise ConflictError(
            "An interview can only be approved from a screened/under-review application"
        )
    # Prevent DUPLICATE invitations: one candidate must not receive two live invitations for
    # the same campaign. A prior DECLINED invitation may be superseded (re-invite is valid),
    # but any still-active (invited/confirmed/reschedule) invitation blocks a second one.
    from sqlalchemy import select

    existing = db.execute(
        select(InterviewInvitation).where(
            InterviewInvitation.organisation_id == application.organisation_id,
            InterviewInvitation.application_id == application.id,
            InterviewInvitation.status != InvitationStatus.DECLINED.value,
        )
    ).scalars().first()
    if existing is not None:
        raise ConflictError(
            "This candidate already has an active interview invitation for this campaign"
        )
    invitation = InterviewInvitation(
        organisation_id=application.organisation_id,
        application_id=application.id,
        campaign_id=application.campaign_id,
        stage_id=stage_id,
        status=InvitationStatus.INVITED.value,
        attendance=AttendanceStatus.PENDING.value,
        approved_by=actor.user_id,
        invited_at=_now(),
        auto_invite=False,
        created_by=actor.user_id,
    )
    db.add(invitation)
    db.flush()

    # Move the application into INTERVIEW_RECOMMENDED via the transition service.
    transition_reason = (
        f"interview approved by authorised actor (override reason: {reason.strip()})"
        if reason and reason.strip()
        else "interview approved by authorised actor"
    )
    transition(db, application=application,
               destination=ApplicationState.INTERVIEW_RECOMMENDED,
               reason=transition_reason, actor=actor)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id, actor_id=actor.user_id,
            action="interview.invitation_approved", entity_type="interview_invitation",
            entity_id=str(invitation.id), new_state_ref="invited",
            reason=reason.strip() if reason and reason.strip() else None,
            security_context="candidate_communication_impact",
        ),
    )
    return invitation


def assign_slot_and_confirm(
    db: Session, *, actor: AuthenticatedActor, invitation_id: uuid.UUID, slot_id: uuid.UUID,
) -> InterviewInvitation:
    """Assign a slot to an invitation and confirm it (enforcing capacity)."""
    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    slot = db.get(InterviewSlot, slot_id)
    if slot is None or slot.organisation_id != actor.organisation_id:
        raise NotFoundError("Slot not found")
    if not slot.has_capacity:
        raise ConflictError("This interview slot is full")

    invitation.slot_id = slot.id
    invitation.stage_id = slot.stage_id
    invitation.status = InvitationStatus.CONFIRMED.value
    invitation.confirmed_at = _now()
    slot.confirmed_count += 1
    db.flush()

    application = db.get(Application, invitation.application_id)
    if (
        application is not None
        and application.state == ApplicationState.INTERVIEW_RECOMMENDED.value
    ):
        transition(db, application=application,
                   destination=ApplicationState.INTERVIEW_SCHEDULED,
                   reason="interview slot confirmed", actor=actor)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="interview.slot_confirmed", entity_type="interview_invitation",
            entity_id=str(invitation.id), new_state_ref="confirmed",
        ),
    )
    return invitation


def record_attendance(
    db: Session, *, actor: AuthenticatedActor, invitation_id: uuid.UUID, attended: bool,
) -> InterviewInvitation:
    """LEGACY attendance recording (Attended / No-show), retained for backward
    compatibility and any historical caller. The current Interview Panel uses
    ``check_in`` / ``check_out`` instead. New code should not call this."""
    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    invitation.attendance = (
        AttendanceStatus.ATTENDED.value if attended else AttendanceStatus.NO_SHOW.value
    )
    db.flush()

    application = db.get(Application, invitation.application_id)
    if application is not None and application.state == ApplicationState.INTERVIEW_SCHEDULED.value:
        destination = ApplicationState.ATTENDED if attended else ApplicationState.NO_SHOW
        transition(db, application=application, destination=destination,
                   reason="attendance recorded", actor=actor)
    return invitation


def _invitation_for_application(
    db: Session, *, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> InterviewInvitation | None:
    """Most-recent interview invitation for an application in this organisation."""
    from sqlalchemy import select

    return db.execute(
        select(InterviewInvitation)
        .where(
            InterviewInvitation.organisation_id == organisation_id,
            InterviewInvitation.application_id == application_id,
        )
        .order_by(InterviewInvitation.created_at.desc())
    ).scalars().first()


def check_in(
    db: Session, *, actor: AuthenticatedActor, invitation_id: uuid.UUID,
) -> InterviewInvitation:
    """Interview Panel checks a candidate in on interview day (Req: Check In).

    Moves the application INTERVIEW_SCHEDULED -> CHECKED_IN and stamps ``checked_in_at``.
    Checking in only records that the interview STARTED — it never marks the interview
    attended/completed. Duplicate check-ins are rejected (idempotency guard): a candidate
    already checked in (or further along) cannot be checked in again.
    """
    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    if invitation.checked_in_at is not None:
        raise ConflictError("This candidate has already been checked in")

    application = db.get(Application, invitation.application_id)
    if application is None or application.organisation_id != actor.organisation_id:
        raise NotFoundError("Application not found")
    if application.state != ApplicationState.INTERVIEW_SCHEDULED.value:
        raise ConflictError(
            "Only a scheduled candidate who has not yet checked in can be checked in"
        )

    invitation.checked_in_at = _now()
    invitation.attendance = AttendanceStatus.CHECKED_IN.value
    db.flush()

    transition(db, application=application, destination=ApplicationState.CHECKED_IN,
               reason="candidate checked in for interview", actor=actor)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="interview.checked_in", entity_type="interview_invitation",
            entity_id=str(invitation.id), new_state_ref="checked_in",
        ),
    )
    return invitation


def check_out(
    db: Session, *, actor: AuthenticatedActor, invitation_id: uuid.UUID,
) -> InterviewInvitation:
    """Interview Panel checks a candidate out once the interview is finished (Req: Check
    Out). Separate event from assessment submission.

    Requires the assessment to have been submitted first: the application must be in the
    ASSESSED state (reached only after ``assessment.submit``). Moves ASSESSED ->
    CHECKED_OUT and stamps ``checked_out_at``. This is what makes the candidate visible as
    "interview attended/completed" in Recruiter Admin. Duplicate check-outs are rejected.
    """
    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    if invitation.checked_in_at is None:
        raise ConflictError("This candidate has not been checked in")
    if invitation.checked_out_at is not None:
        raise ConflictError("This candidate has already been checked out")

    application = db.get(Application, invitation.application_id)
    if application is None or application.organisation_id != actor.organisation_id:
        raise NotFoundError("Application not found")
    if application.state != ApplicationState.ASSESSED.value:
        # Assessment-before-checkout is enforced here: a checked-in candidate must be
        # assessed (-> ASSESSED) before they can be checked out.
        raise ConflictError(
            "The assessment must be submitted before the candidate can be checked out"
        )

    invitation.checked_out_at = _now()
    invitation.attendance = AttendanceStatus.CHECKED_OUT.value
    db.flush()

    transition(db, application=application, destination=ApplicationState.CHECKED_OUT,
               reason="candidate checked out; interview completed", actor=actor)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="interview.checked_out", entity_type="interview_invitation",
            entity_id=str(invitation.id), new_state_ref="checked_out",
        ),
    )
    return invitation


def _ensure_walk_in_slot(
    db: Session, *, organisation_id: uuid.UUID, campaign_id: uuid.UUID, actor_id: uuid.UUID
) -> InterviewSlot:
    """Find an existing slot with capacity for the campaign, or create a default walk-in one.

    Lets a recruiter run the whole interview booking in one step for walk-in drives, without
    manually pre-creating a stage and slot. The created slot is a normal, audited slot.
    """
    for slot in list_slots(db, organisation_id, campaign_id):
        if slot.has_capacity:
            return slot

    stages = list_stages(db, organisation_id, campaign_id)
    if stages:
        stage = stages[0]
    else:
        stage = create_stage(
            db, organisation_id=organisation_id, campaign_id=campaign_id,
            name="Walk-in interview", sequence=1, actor_id=actor_id,
        )
    return create_slot(
        db, organisation_id=organisation_id, stage_id=stage.id,
        slot_date=_now().date(), start_time="walk-in", location="Walk-in",
        mode="in_person", capacity=50, actor_id=actor_id,
    )


def record_walk_in_interview(
    db: Session, *, actor: AuthenticatedActor, application: Application,
    reason: str | None = None,
) -> InterviewInvitation:
    """One-step express path for a walk-in interview: approve the invitation (if needed) and
    assign/confirm a slot, so the candidate reaches INTERVIEW_SCHEDULED and appears on the
    Interview Panel's list immediately. Runs the SAME audited transitions as the manual
    steps, in order; it does not bypass the state machine. Attendance is left to the panel.

    ``reason`` is an optional justification passed through to the invitation-approval audit
    trail. It is used when an authorised actor selects a below-50 candidate for interview
    from the Review Queue (a screening override): the reason is required by the caller and
    recorded, so the override is explainable (security.md).
    """
    # 1. Ensure an invitation exists (approve from SCREENED/MANUAL_REVIEW if needed).
    from sqlalchemy import select

    invitation = db.execute(
        select(InterviewInvitation).where(
            InterviewInvitation.organisation_id == actor.organisation_id,
            InterviewInvitation.application_id == application.id,
        )
    ).scalars().first()

    if application.state in {
        ApplicationState.SCREENED.value, ApplicationState.MANUAL_REVIEW.value,
    } and invitation is None:
        invitation = approve_invitation(
            db, actor=actor, application=application, reason=reason
        )
    if invitation is None:
        raise ConflictError(
            "This candidate has no interview invitation and is not in a state to create one"
        )

    # 2. Ensure a confirmed slot (→ INTERVIEW_SCHEDULED).
    if application.state == ApplicationState.INTERVIEW_RECOMMENDED.value:
        slot = _ensure_walk_in_slot(
            db, organisation_id=actor.organisation_id, campaign_id=application.campaign_id,
            actor_id=actor.user_id,
        )
        invitation = assign_slot_and_confirm(
            db, actor=actor, invitation_id=invitation.id, slot_id=slot.id
        )

    # The candidate is now INTERVIEW_SCHEDULED and appears on the Interview Panel's list.
    # Attendance is NOT marked here: that is the panel's responsibility (they confirm the
    # candidate showed up, then assess). This keeps the recruiter's job to scheduling and
    # the panel's job to attendance + assessment.
    return invitation
