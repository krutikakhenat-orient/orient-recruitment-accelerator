"""Interview workflow HTTP router (thin). Object-level campaign authz throughout."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.applications.models import Application
from app.modules.identity.models import User
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import (
    require_assignment_management,
    require_campaign_permission,
    require_permission,
)
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews import assignment_service, service
from app.modules.interviews.models import InterviewSlot, InterviewStage
from app.modules.interviews.schemas import (
    AssignmentCreate,
    AssignmentOverviewRead,
    AssignmentRead,
    AssignmentUpdate,
    AttendanceRequest,
    InvitationApprove,
    InvitationRead,
    MyAssignmentRead,
    SlotAssign,
    SlotCreate,
    SlotRead,
    StageCreate,
    StageRead,
)

router = APIRouter(prefix="/api/v1/interviews", tags=["interviews"])


def _assignment_read(db: Session, assignment: object) -> AssignmentRead:
    """Serialise an InterviewAssignment to its metadata DTO, resolving the interviewer's
    display name. No candidate data is read or returned."""
    from app.modules.interviews.models import InterviewAssignment

    assert isinstance(assignment, InterviewAssignment)
    interviewer = db.get(User, assignment.interviewer_id)
    data = AssignmentRead.model_validate(assignment)
    if interviewer is not None:
        data = data.model_copy(update={"interviewer_name": interviewer.display_name})
    return data


@router.get(
    "/campaigns/{campaign_id}/assignments", response_model=list[AssignmentRead]
)
def list_campaign_assignments(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[AssignmentRead]:
    """List active interviewer assignments for a campaign (assignment metadata only — no
    candidate profiles, resumes, or scorecards). Requires interview.assign + management
    authorisation for this campaign."""
    require_assignment_management(actor, campaign_id)
    rows = assignment_service.list_assignments(
        db, organisation_id=actor.organisation_id, campaign_id=campaign_id
    )
    return [_assignment_read(db, a) for a in rows]


@router.post(
    "/campaigns/{campaign_id}/assignments", response_model=AssignmentRead, status_code=201
)
def create_campaign_assignment(
    campaign_id: uuid.UUID,
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AssignmentRead:
    """Assign an interviewer to a campaign and optional stage. Idempotent (reactivates an
    existing inactive assignment rather than duplicating). Requires interview.assign +
    management authorisation for this campaign. The organisation and assigner are derived
    from the session, never the client."""
    require_assignment_management(actor, campaign_id)
    assignment = assignment_service.create_assignment(
        db,
        organisation_id=actor.organisation_id,
        campaign_id=campaign_id,
        interviewer_id=payload.interviewer_id,
        stage_id=payload.stage_id,
        assigned_by=actor.user_id,
    )
    return _assignment_read(db, assignment)


@router.patch("/assignments/{assignment_id}", response_model=AssignmentRead)
def update_campaign_assignment(
    assignment_id: uuid.UUID,
    payload: AssignmentUpdate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AssignmentRead:
    """Change an assignment's stage scope. Requires interview.assign + management
    authorisation for the assignment's campaign."""
    assignment = assignment_service.get_assignment(
        db, organisation_id=actor.organisation_id, assignment_id=assignment_id
    )
    require_assignment_management(actor, assignment.campaign_id)
    updated = assignment_service.update_assignment_stage(
        db,
        organisation_id=actor.organisation_id,
        assignment_id=assignment_id,
        stage_id=payload.stage_id,
        actor_id=actor.user_id,
    )
    return _assignment_read(db, updated)


@router.delete("/assignments/{assignment_id}", status_code=204)
def remove_campaign_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> Response:
    """Soft-deactivate an assignment (preserves history and submitted assessments).
    Requires interview.assign + management authorisation for the assignment's campaign."""
    assignment = assignment_service.get_assignment(
        db, organisation_id=actor.organisation_id, assignment_id=assignment_id
    )
    require_assignment_management(actor, assignment.campaign_id)
    assignment_service.deactivate_assignment(
        db,
        organisation_id=actor.organisation_id,
        assignment_id=assignment_id,
        actor_id=actor.user_id,
    )
    return Response(status_code=204)


@router.get("/my-assignments", response_model=list[MyAssignmentRead])
def my_assignments(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[MyAssignmentRead]:
    """The authenticated interviewer's own active assignments, as campaign buckets (keyed by
    campaign UUID). Requires assessment.submit. Drives the panel's campaign-bucket list."""
    require_permission(actor, Permission.ASSESSMENT_SUBMIT)
    rows = assignment_service.active_assignments_for_interviewer(
        db, organisation_id=actor.organisation_id, interviewer_id=actor.user_id
    )
    from app.modules.campaigns.models import Campaign

    out: list[MyAssignmentRead] = []
    for a in rows:
        campaign = db.get(Campaign, a.campaign_id)
        campaign_label = (
            (campaign.position_title or campaign.name) if campaign is not None
            else str(a.campaign_id)
        )
        stage_name: str | None = None
        if a.stage_id is not None:
            stage = db.get(InterviewStage, a.stage_id)
            stage_name = stage.name if stage is not None else None
        out.append(
            MyAssignmentRead(
                campaign_id=a.campaign_id,
                campaign_name=campaign_label,
                stage_id=a.stage_id,
                stage_name=stage_name,
            )
        )
    return out


@router.get("/assignments", response_model=list[AssignmentOverviewRead])
def list_all_assignments(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[AssignmentOverviewRead]:
    """Organisation-wide interviewer-assignment overview for administration (the System
    Admin "assigned users" view). Requires `interview.assign`. Returns ONLY assignment +
    user/campaign/stage metadata — never candidate profiles, resumes, contact details,
    scores, rankings, or assessments. Includes inactive assignments so status is visible.
    """
    require_permission(actor, Permission.INTERVIEW_ASSIGN)

    from app.modules.campaigns.models import Campaign

    rows = assignment_service.list_all_assignments(
        db, organisation_id=actor.organisation_id, include_inactive=True
    )
    # Resolve display labels with small per-id caches (no candidate data is touched).
    campaign_cache: dict[uuid.UUID, Campaign | None] = {}
    stage_cache: dict[uuid.UUID, InterviewStage | None] = {}
    user_cache: dict[uuid.UUID, User | None] = {}

    def _campaign(cid: uuid.UUID) -> Campaign | None:
        if cid not in campaign_cache:
            campaign_cache[cid] = db.get(Campaign, cid)
        return campaign_cache[cid]

    def _stage(sid: uuid.UUID) -> InterviewStage | None:
        if sid not in stage_cache:
            stage_cache[sid] = db.get(InterviewStage, sid)
        return stage_cache[sid]

    def _user(uid: uuid.UUID) -> User | None:
        if uid not in user_cache:
            user_cache[uid] = db.get(User, uid)
        return user_cache[uid]

    out: list[AssignmentOverviewRead] = []
    for a in rows:
        campaign = _campaign(a.campaign_id)
        interviewer = _user(a.interviewer_id)
        stage = _stage(a.stage_id) if a.stage_id is not None else None
        out.append(
            AssignmentOverviewRead(
                id=a.id,
                interviewer_id=a.interviewer_id,
                interviewer_name=interviewer.display_name if interviewer else None,
                interviewer_email=interviewer.email if interviewer else None,
                interviewer_role_names=sorted(
                    {ur.role.name for ur in interviewer.roles if ur.role is not None}
                ) if interviewer else [],
                campaign_id=a.campaign_id,
                campaign_name=(
                    (campaign.position_title or campaign.name) if campaign else None
                ),
                stage_id=a.stage_id,
                stage_name=stage.name if stage else None,
                is_active=a.is_active,
            )
        )
    return out


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
