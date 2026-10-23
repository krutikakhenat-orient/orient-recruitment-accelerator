"""Hiring decision service (Req 10.4).

approve_decision performs the final disposition. Select/reject require
hiring_decision.approve (enforced at the router); hold uses hiring_decision.recommend.
The application state change goes through the application transition service, which emits
the audit event and records candidate-communication impact.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.applications.transition_service import transition
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.decisions.models import DecisionStatus, DecisionType, HiringDecision
from app.modules.identity.schemas import AuthenticatedActor

if TYPE_CHECKING:
    from app.modules.assessments.models import Assessment

_DECISION_TO_STATE = {
    DecisionType.SELECT: ApplicationState.SELECTED,
    DecisionType.REJECT: ApplicationState.REJECTED,
    DecisionType.HOLD: ApplicationState.HOLD,
    DecisionType.WITHDRAW: ApplicationState.WITHDRAWN,
}


def list_pending_decisions(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_ids: set[uuid.UUID],
) -> list[tuple[Application, str, list[Assessment]]]:
    """Assessed candidates awaiting a hiring decision, with the panel's assessments.

    Restricted to the campaigns the actor is assigned to (object-level authz). Returns a
    list of (application, candidate_name, assessments) so the hiring manager / recruiter
    admin can review the panel's verdict and decide. This is the handoff from the interview
    panel to the decision-maker.
    """
    from sqlalchemy import select

    from app.modules.assessments.models import Assessment

    stmt = (
        select(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.state == ApplicationState.ASSESSED.value,
        )
        .order_by(Application.created_at.desc())
    )
    apps = [a for a in db.execute(stmt).scalars() if a.campaign_id in campaign_ids]

    results = []
    for app in apps:
        name = app.answers.get("full_name") if isinstance(app.answers, dict) else None
        assessments = list(
            db.execute(
                select(Assessment).where(Assessment.application_id == app.id)
            ).scalars()
        )
        results.append((app, str(name) if name else "Candidate", assessments))
    return results


# Application states that represent a final hiring outcome.
_OUTCOME_STATES = {
    ApplicationState.SELECTED.value,
    ApplicationState.REJECTED.value,
    ApplicationState.HOLD.value,
}


def list_outcomes(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_ids: set[uuid.UUID],
) -> list[dict[str, object]]:
    """Decided candidates (selected / rejected / hold) with the decision's reason and the
    candidate reference, scoped to the actor's assigned campaigns. Contact details are NOT
    included here — they are revealed per-candidate through the audited PII endpoint, so an
    outcomes overview never leaks raw contact data (privacy.md)."""
    from sqlalchemy import select

    from app.modules.campaigns.models import Campaign

    stmt = (
        select(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.state.in_(_OUTCOME_STATES),
        )
        .order_by(Application.updated_at.desc())
    )
    apps = [a for a in db.execute(stmt).scalars() if a.campaign_id in campaign_ids]

    campaign_names: dict[uuid.UUID, str] = {}
    out: list[dict[str, object]] = []
    for app in apps:
        if app.campaign_id not in campaign_names:
            c = db.get(Campaign, app.campaign_id)
            campaign_names[app.campaign_id] = c.name if c is not None else "—"
        name = app.answers.get("full_name") if isinstance(app.answers, dict) else None
        latest = db.execute(
            select(HiringDecision)
            .where(HiringDecision.application_id == app.id)
            .order_by(HiringDecision.created_at.desc())
            .limit(1)
        ).scalars().first()
        out.append(
            {
                "application_id": app.id,
                "candidate_id": app.candidate_id,
                "campaign_name": campaign_names[app.campaign_id],
                "candidate_name": str(name) if name else "Candidate",
                "outcome": app.state,
                "reason": latest.reason if latest is not None else None,
            }
        )
    return out


def record_decision(
    db: Session,
    *,
    actor: AuthenticatedActor,
    application: Application,
    decision_type: DecisionType,
    reason: str,
) -> HiringDecision:
    if not reason or not reason.strip():
        raise ValidationError("A reason is required for a hiring decision")

    destination = _DECISION_TO_STATE[decision_type]
    # Select/reject are only valid after assessment; hold likewise. Withdraw is broad and
    # handled by the transition table's own guards.
    if (
        decision_type in {DecisionType.SELECT, DecisionType.REJECT, DecisionType.HOLD}
        and application.state != ApplicationState.ASSESSED.value
    ):
        raise ConflictError("Select/reject/hold decisions require an assessed application")

    decision = HiringDecision(
        organisation_id=application.organisation_id,
        application_id=application.id,
        campaign_id=application.campaign_id,
        decision_type=decision_type.value,
        status=DecisionStatus.APPROVED.value,
        reason=reason,
        recommended_by=actor.user_id,
        approved_by=actor.user_id,
        created_by=actor.user_id,
    )
    db.add(decision)
    db.flush()

    transition(db, application=application, destination=destination, reason=reason, actor=actor)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id, actor_id=actor.user_id,
            action=f"hiring_decision.{decision_type.value}", entity_type="hiring_decision",
            entity_id=str(decision.id), new_state_ref=destination.value, reason=reason,
        ),
    )
    return decision
