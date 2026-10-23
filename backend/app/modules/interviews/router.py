"""Interview workflow HTTP router (thin). Object-level campaign authz throughout."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.applications.models import Application
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews import service
from app.modules.interviews.models import InterviewSlot, InterviewStage
from app.modules.interviews.schemas import (
    AttendanceRequest,
    InvitationApprove,
    InvitationRead,
    SlotAssign,
    SlotCreate,
    SlotRead,
    StageCreate,
    StageRead,
)

router = APIRouter(prefix="/api/v1/interviews", tags=["interviews"])


@router.get("/stages", response_model=list[StageRead])
def list_stages(
    campaign_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[StageRead]:
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    stages = service.list_stages(db, actor.organisation_id, campaign_id)
    return [StageRead.model_validate(s) for s in stages]


@router.get("/slots", response_model=list[SlotRead])
def list_slots(
    campaign_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[SlotRead]:
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    slots = service.list_slots(db, actor.organisation_id, campaign_id)
    return [SlotRead.model_validate(s) for s in slots]


@router.get("/invitations", response_model=list[InvitationRead])
def list_invitations(
    campaign_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[InvitationRead]:
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    invites = service.list_invitations(db, actor.organisation_id, campaign_id)
    return [InvitationRead.model_validate(i) for i in invites]


@router.post("/stages", response_model=StageRead, status_code=201)
def create_stage(
    payload: StageCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> StageRead:
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, payload.campaign_id)
    stage = service.create_stage(
        db, organisation_id=actor.organisation_id, campaign_id=payload.campaign_id,
        name=payload.name, sequence=payload.sequence, actor_id=actor.user_id,
    )
    return StageRead.model_validate(stage)


@router.post("/slots", response_model=SlotRead, status_code=201)
def create_slot(
    payload: SlotCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> SlotRead:
    stage = db.get(InterviewStage, payload.stage_id)
    if stage is None or stage.organisation_id != actor.organisation_id:
        raise NotFoundError("Interview stage not found")
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, stage.campaign_id)
    slot = service.create_slot(
        db, organisation_id=actor.organisation_id, stage_id=payload.stage_id,
        slot_date=payload.slot_date, start_time=payload.start_time,
        location=payload.location, mode=payload.mode, capacity=payload.capacity,
        actor_id=actor.user_id,
    )
    return SlotRead.model_validate(slot)


def _require_override_reason_if_under_review(
    application: Application, reason: str | None
) -> None:
    """A candidate in MANUAL_REVIEW has NOT met the automatic bar, so selecting them for
    interview is an override of the screening outcome. Per security.md, such an override
    requires BOTH authority (checked separately) and a recorded reason. Candidates already
    SCREENED (clean) may be selected without a reason."""
    from app.core.errors import ValidationError
    from app.modules.applications.states import ApplicationState

    if application.state == ApplicationState.MANUAL_REVIEW.value and not (
        reason and reason.strip()
    ):
        raise ValidationError(
            "A reason is required to select a candidate who is under review "
            "(below the automatic threshold) for interview."
        )


@router.post("/invitations/approve", response_model=InvitationRead, status_code=201)
def approve_invitation(
    payload: InvitationApprove,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InvitationRead:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(actor, Permission.INTERVIEW_APPROVE, application.campaign_id)
    _require_override_reason_if_under_review(application, payload.reason)
    invitation = service.approve_invitation(
        db, actor=actor, application=application, stage_id=payload.stage_id,
        reason=payload.reason,
    )
    return InvitationRead.model_validate(invitation)


@router.post("/invitations/walk-in", response_model=InvitationRead, status_code=201)
def record_walk_in_interview(
    payload: InvitationApprove,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InvitationRead:
    """Express path: approve + schedule (auto slot) in one call, so the candidate reaches
    INTERVIEW_SCHEDULED and appears on the Interview Panel immediately. Attendance is
    recorded by the panel. Requires interview.approve AND interview.schedule (both held by
    Recruiter Admin) plus campaign assignment.

    Used both for same-day walk-ins and for the Recruitment-Admin "Select for interview"
    action on below-threshold (under-review) candidates — the latter is a screening override
    and therefore requires a reason, enforced here."""
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(actor, Permission.INTERVIEW_APPROVE, application.campaign_id)
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, application.campaign_id)
    _require_override_reason_if_under_review(application, payload.reason)
    invitation = service.record_walk_in_interview(
        db, actor=actor, application=application, reason=payload.reason
    )
    return InvitationRead.model_validate(invitation)


@router.post("/invitations/{invitation_id}/assign-slot", response_model=InvitationRead)
def assign_slot(
    invitation_id: uuid.UUID,
    payload: SlotAssign,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InvitationRead:
    slot = db.get(InterviewSlot, payload.slot_id)
    if slot is None or slot.organisation_id != actor.organisation_id:
        raise NotFoundError("Slot not found")
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, slot.stage.campaign_id)
    invitation = service.assign_slot_and_confirm(
        db, actor=actor, invitation_id=invitation_id, slot_id=payload.slot_id
    )
    return InvitationRead.model_validate(invitation)


@router.post("/invitations/{invitation_id}/attendance", response_model=InvitationRead)
def record_attendance(
    invitation_id: uuid.UUID,
    payload: AttendanceRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InvitationRead:
    from app.modules.interviews.models import InterviewInvitation

    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    # Attendance is recorded by the Interview Panel (assessment.submit). Panel members are
    # invited to the specific candidate, not assigned to the campaign, so this is a global
    # permission check, not a campaign-scoped one — mirroring assessment submission. The
    # INTERVIEW_SCHEDULED-state guard in the transition service scopes it to genuinely
    # scheduled candidates.
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    updated = service.record_attendance(
        db, actor=actor, invitation_id=invitation_id, attended=payload.attended
    )
    return InvitationRead.model_validate(updated)


@router.post("/invitations/{invitation_id}/check-in", response_model=InvitationRead)
def check_in(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InvitationRead:
    """Interview Panel checks a candidate in on interview day. Requires assessment.submit
    (panel members are invited to the candidate, not campaign-assigned — same model as
    assessment submission). The INTERVIEW_SCHEDULED-state guard in the service scopes this
    to genuinely scheduled candidates, and duplicate check-ins are rejected."""
    from app.modules.interviews.models import InterviewInvitation

    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    updated = service.check_in(db, actor=actor, invitation_id=invitation_id)
    return InvitationRead.model_validate(updated)


@router.post("/invitations/{invitation_id}/check-out", response_model=InvitationRead)
def check_out(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InvitationRead:
    """Interview Panel checks a candidate out once the interview is finished. Requires
    assessment.submit. The service enforces that the assessment was already submitted
    (ASSESSED state) before checkout, and rejects duplicate check-outs."""
    from app.modules.interviews.models import InterviewInvitation

    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != actor.organisation_id:
        raise NotFoundError("Invitation not found")
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    updated = service.check_out(db, actor=actor, invitation_id=invitation_id)
    return InvitationRead.model_validate(updated)
