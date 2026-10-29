"""Hiring decision HTTP router (thin).

Select/reject require hiring_decision.approve; hold/withdraw require
hiring_decision.recommend. All require object-level campaign authorisation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.decisions import service
from app.modules.decisions.models import DecisionType
from app.modules.decisions.schemas import (
    AssessmentSummary,
    DecisionRead,
    DecisionRequest,
    OutcomeRead,
    PendingDecisionRead,
)
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])

_APPROVE_DECISIONS = {DecisionType.SELECT, DecisionType.REJECT}


@router.get("/pending", response_model=list[PendingDecisionRead])
def list_pending_decisions(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[PendingDecisionRead]:
    """Candidates whose interview is concluded (assessed or checked out) and awaiting a
    hiring decision, scoped to the actor's assigned campaigns, each with the interview
    panel's assessment(s). This is the panel → decision handoff. Visible to anyone who can
    recommend or approve a hiring decision."""
    require_permission(actor, Permission.HIRING_DECISION_RECOMMEND)
    rows = service.list_pending_decisions(
        db, organisation_id=actor.organisation_id, campaign_ids=actor.assigned_campaign_ids
    )
    out: list[PendingDecisionRead] = []
    for app, name, assessments in rows:
        out.append(
            PendingDecisionRead(
                application_id=app.id,
                campaign_id=app.campaign_id,
                candidate_name=name,
                assessments=[
                    AssessmentSummary(
                        recommendation=a.recommendation,
                        criteria_scores=a.criteria_scores,
                        interview_notes=a.interview_notes,
                        conflict_declared=a.conflict_declared,
                    )
                    for a in assessments
                ],
            )
        )
    return out


@router.get("/outcomes", response_model=list[OutcomeRead])
def list_outcomes(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[OutcomeRead]:
    """Decided candidates (selected / rejected / hold) in the actor's assigned campaigns,
    with the decision reason. Requires candidate.view. Contact details are revealed per
    candidate via the audited candidate.view_pii endpoint, never in this overview."""
    require_permission(actor, Permission.CANDIDATE_VIEW)
    rows = service.list_outcomes(
        db, organisation_id=actor.organisation_id, campaign_ids=actor.assigned_campaign_ids
    )
    return [OutcomeRead(**row) for row in rows]  # type: ignore[arg-type]


@router.post("", response_model=DecisionRead, status_code=201)
def record_decision(
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DecisionRead:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    required = (
        Permission.HIRING_DECISION_APPROVE
        if payload.decision_type in _APPROVE_DECISIONS
        else Permission.HIRING_DECISION_RECOMMEND
    )
    require_campaign_permission(actor, required, application.campaign_id)
    decision = service.record_decision(
        db, actor=actor, application=application, decision_type=payload.decision_type,
        reason=payload.reason,
    )
    return DecisionRead.model_validate(decision)
