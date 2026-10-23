"""Application TransitionService — single choke point for application status changes.

Mirrors the campaign TransitionService: the transition must exist in the table, the actor
(if the transition requires a permission) must hold it AND be assigned to the campaign, a
reason is required, and an audit event is emitted. System/pipeline transitions
(``permission is None``) are performed internally without a user permission check but still
require a reason and are audited.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import InvalidTransitionError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState, find_transition
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor


def transition(
    db: Session,
    *,
    application: Application,
    destination: ApplicationState,
    reason: str,
    actor: AuthenticatedActor | None = None,
) -> Application:
    source = ApplicationState(application.state)
    rule = find_transition(source, destination)
    if rule is None:
        raise InvalidTransitionError(
            f"Application transition {source.value} -> {destination.value} is not permitted"
        )
    if not reason or not reason.strip():
        raise ValidationError("A transition reason is required")

    if rule.permission is not None:
        if actor is None:
            raise InvalidTransitionError(
                f"Transition '{rule.name}' requires an authorised actor"
            )
        if rule.campaign_scoped:
            require_campaign_permission(actor, rule.permission, application.campaign_id)
        else:
            # Actor is authorised by the global permission only (e.g. an invited interview
            # panel member who is not a campaign assignee). The source-state guard scopes
            # the action to genuinely-interviewed candidates.
            require_permission(actor, rule.permission)

    application.state = destination.value
    application.disposition_reason = reason
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id,
            actor_id=actor.user_id if actor else None,
            action=f"application.transition.{rule.name}",
            entity_type="application",
            entity_id=str(application.id),
            previous_state_ref=source.value,
            new_state_ref=destination.value,
            reason=reason,
            security_context=(
                "candidate_communication_impact"
                if rule.candidate_communication_impact
                else None
            ),
        ),
    )
    return application
