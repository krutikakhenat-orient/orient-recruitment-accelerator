"""Interviewer assignment service.

Governs which interview-panel members are assigned to which campaign (and, optionally,
which stage), and provides the authorisation helpers that the panel worklist and every
interview-day action use to scope a panel member to ONLY their assigned work.

Design (see InterviewAssignment model):
  * campaign_id is required; stage_id NULL = the whole campaign.
  * Assignment is idempotent: a repeated request for the same (campaign, stage, interviewer)
    reactivates the existing row rather than inserting a duplicate (unique constraint).
  * Soft removal (is_active=False) preserves history and never touches submitted assessments.

Security notes:
  * Managing assignments requires ``interview.assign`` (System Admin, and Recruiter Admin for
    campaigns it is assigned to). ``interview.assign`` confers NO candidate-content access —
    this service returns only assignment metadata, never candidate profiles/resumes/scores.
  * Authorisation for a panel member is derived from the authenticated session's user id;
    client-supplied user/org ids are never trusted.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns.models import Campaign
from app.modules.identity.models import User
from app.modules.identity.permissions import Permission
from app.modules.identity.repository import effective_permissions
from app.modules.interviews.models import InterviewAssignment, InterviewStage


def _get_campaign_in_org(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.organisation_id != organisation_id:
        raise NotFoundError("Campaign not found")
    return campaign


def _validate_stage(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID,
    stage_id: uuid.UUID | None,
) -> None:
    if stage_id is None:
        return
    stage = db.get(InterviewStage, stage_id)
    if (
        stage is None
        or stage.organisation_id != organisation_id
        or stage.campaign_id != campaign_id
    ):
        raise ValidationError("The interview stage does not belong to this campaign")


def _validate_interviewer(
    db: Session, organisation_id: uuid.UUID, interviewer_id: uuid.UUID
) -> User:
    """The interviewer must be an active user in the SAME organisation who can submit
    assessments (holds assessment.submit). We never trust a cross-org interviewer id."""
    user = db.get(User, interviewer_id)
    if user is None or user.organisation_id != organisation_id:
        raise NotFoundError("Interviewer user not found")
    if not user.is_active:
        raise ValidationError("The interviewer account is not active")
    if Permission.ASSESSMENT_SUBMIT.value not in effective_permissions(db, user):
        raise ValidationError(
            "The selected user cannot be assigned as an interviewer "
            "(they do not hold the interview-panel assessment permission)"
        )
    return user


def create_assignment(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    interviewer_id: uuid.UUID,
    stage_id: uuid.UUID | None,
    assigned_by: uuid.UUID,
) -> InterviewAssignment:
    """Assign an interviewer to a campaign/stage. Idempotent: reactivates an existing row
    for the same (campaign, stage, interviewer) rather than creating a duplicate."""
    _get_campaign_in_org(db, organisation_id, campaign_id)
    _validate_stage(db, organisation_id, campaign_id, stage_id)
    _validate_interviewer(db, organisation_id, interviewer_id)

    existing = db.execute(
        select(InterviewAssignment).where(
            InterviewAssignment.organisation_id == organisation_id,
            InterviewAssignment.campaign_id == campaign_id,
            InterviewAssignment.stage_id.is_(stage_id)
            if stage_id is None
            else InterviewAssignment.stage_id == stage_id,
            InterviewAssignment.interviewer_id == interviewer_id,
        )
    ).scalars().first()

    reactivated = False
    if existing is not None:
        assignment = existing
        if not existing.is_active:
            existing.is_active = True
            existing.assigned_by = assigned_by
            existing.updated_by = assigned_by
            reactivated = True
            db.flush()
    else:
        assignment = InterviewAssignment(
            organisation_id=organisation_id,
            campaign_id=campaign_id,
            stage_id=stage_id,
            interviewer_id=interviewer_id,
            assigned_by=assigned_by,
            is_active=True,
            created_by=assigned_by,
        )
        db.add(assignment)
        db.flush()

    # Audit: only on a genuine state change (new row or reactivation), never duplicating a
    # no-op repeat request. Metadata only — no candidate information.
    if existing is None or reactivated:
        record_event(
            db,
            AuditEventWrite(
                organisation_id=organisation_id,
                actor_id=assigned_by,
                action="interview.assignment_added",
                entity_type="interview_assignment",
                entity_id=str(assignment.id),
                new_state_ref="active",
                security_context=(
                    f"campaign={campaign_id};stage={stage_id or 'all'};"
                    f"interviewer={interviewer_id}"
                ),
            ),
        )
    return assignment


def list_assignments(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    include_inactive: bool = False,
) -> list[InterviewAssignment]:
    """Assignment metadata for a campaign (newest first). Caller authorises management."""
    stmt = select(InterviewAssignment).where(
        InterviewAssignment.organisation_id == organisation_id,
        InterviewAssignment.campaign_id == campaign_id,
    )
    if not include_inactive:
        stmt = stmt.where(InterviewAssignment.is_active.is_(True))
    stmt = stmt.order_by(InterviewAssignment.created_at.desc())
    return list(db.execute(stmt).scalars())


def list_all_assignments(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    include_inactive: bool = True,
) -> list[InterviewAssignment]:
    """Every interviewer assignment in the organisation (newest first), for the System Admin
    overview. Metadata only — this never reads candidate data. Caller authorises management.
    Includes inactive rows by default so the admin view can show assignment status/history.
    """
    stmt = select(InterviewAssignment).where(
        InterviewAssignment.organisation_id == organisation_id,
    )
    if not include_inactive:
        stmt = stmt.where(InterviewAssignment.is_active.is_(True))
    stmt = stmt.order_by(InterviewAssignment.created_at.desc())
    return list(db.execute(stmt).scalars())


def get_assignment(
    db: Session, *, organisation_id: uuid.UUID, assignment_id: uuid.UUID
) -> InterviewAssignment:
    assignment = db.get(InterviewAssignment, assignment_id)
    if assignment is None or assignment.organisation_id != organisation_id:
        raise NotFoundError("Interview assignment not found")
    return assignment


def update_assignment_stage(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    assignment_id: uuid.UUID,
    stage_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> InterviewAssignment:
    """Change an assignment's stage scope (NULL = whole campaign). The interviewer and
    campaign are immutable; to move an interviewer, deactivate and create a new one."""
    assignment = get_assignment(
        db, organisation_id=organisation_id, assignment_id=assignment_id
    )
    _validate_stage(db, organisation_id, assignment.campaign_id, stage_id)

    # Guard the unique scope: changing the stage must not collide with another active row
    # for the same (campaign, stage, interviewer).
    if stage_id != assignment.stage_id:
        clash = db.execute(
            select(InterviewAssignment).where(
                InterviewAssignment.organisation_id == organisation_id,
                InterviewAssignment.campaign_id == assignment.campaign_id,
                InterviewAssignment.interviewer_id == assignment.interviewer_id,
                InterviewAssignment.stage_id.is_(stage_id)
                if stage_id is None
                else InterviewAssignment.stage_id == stage_id,
                InterviewAssignment.id != assignment.id,
            )
        ).scalars().first()
        if clash is not None:
            raise ValidationError(
                "This interviewer already has an assignment for that stage scope"
            )

    previous = "all" if assignment.stage_id is None else str(assignment.stage_id)
    assignment.stage_id = stage_id
    assignment.updated_by = actor_id
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="interview.assignment_updated",
            entity_type="interview_assignment",
            entity_id=str(assignment.id),
            previous_state_ref=previous,
            new_state_ref="all" if stage_id is None else str(stage_id),
        ),
    )
    return assignment


def deactivate_assignment(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    assignment_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> InterviewAssignment:
    """Soft-remove an assignment. History and any submitted assessments are preserved."""
    assignment = get_assignment(
        db, organisation_id=organisation_id, assignment_id=assignment_id
    )
    if assignment.is_active:
        assignment.is_active = False
        assignment.updated_by = actor_id
        db.flush()
        record_event(
            db,
            AuditEventWrite(
                organisation_id=organisation_id,
                actor_id=actor_id,
                action="interview.assignment_removed",
                entity_type="interview_assignment",
                entity_id=str(assignment.id),
                previous_state_ref="active",
                new_state_ref="inactive",
            ),
        )
    return assignment


# --------------------------------------------------------------------------------------
# Authorisation helpers (used by the worklist + every interview-day action)
# --------------------------------------------------------------------------------------
def active_assignments_for_interviewer(
    db: Session, *, organisation_id: uuid.UUID, interviewer_id: uuid.UUID
) -> list[InterviewAssignment]:
    """All ACTIVE assignments for one interviewer in one organisation."""
    return list(
        db.execute(
            select(InterviewAssignment).where(
                InterviewAssignment.organisation_id == organisation_id,
                InterviewAssignment.interviewer_id == interviewer_id,
                InterviewAssignment.is_active.is_(True),
            )
        ).scalars()
    )


def interviewer_assigned_campaign_ids(
    db: Session, *, organisation_id: uuid.UUID, interviewer_id: uuid.UUID
) -> set[uuid.UUID]:
    """The set of campaign ids the interviewer has an active assignment to."""
    return {
        a.campaign_id
        for a in active_assignments_for_interviewer(
            db, organisation_id=organisation_id, interviewer_id=interviewer_id
        )
    }


def is_interviewer_assigned_to_campaign_stage(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    interviewer_id: uuid.UUID,
    campaign_id: uuid.UUID,
    stage_id: uuid.UUID | None = None,
) -> bool:
    """True if the interviewer has an active assignment covering this campaign (and, when a
    stage is given, either a campaign-wide assignment (stage_id NULL) OR one scoped to that
    stage). A stage-scoped assignment never grants access to a different stage.
    """
    assignments = active_assignments_for_interviewer(
        db, organisation_id=organisation_id, interviewer_id=interviewer_id
    )
    for a in assignments:
        if a.campaign_id != campaign_id:
            continue
        if a.stage_id is None:
            return True  # whole-campaign assignment covers any stage
        if stage_id is not None and a.stage_id == stage_id:
            return True
    return False
