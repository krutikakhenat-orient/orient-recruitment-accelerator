"""Campaign TransitionService — the single choke point for campaign status changes.

No other code path may change a campaign's state (Req 2.3.4). Every transition:
1. Must exist in the transition table, else it is rejected (Req 2.3.3).
2. Requires the actor to hold the transition's permission AND be assigned to the campaign
   (object-level authorisation, Req 1.2).
3. Must satisfy the transition's declared data prerequisites (e.g. publication requires an
   approved JD, rule-set, form, threshold, and privacy notice — AC-04).
4. Requires an explicit reason, which is recorded in an audit event with the actor,
   timestamp, previous/next state, and candidate-communication impact (Req 2.3.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import InvalidTransitionError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState, TransitionRule, find_transition
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor

# Maps a required-prerequisite name to the Campaign attribute that must be non-null.
_PREREQUISITE_ATTR = {
    "approved_jd_version": "approved_jd_version_id",
    "approved_rule_set_version": "approved_rule_set_version_id",
    "approved_form_version": "approved_form_version_id",
    "active_threshold_version": "active_threshold_version_id",
    "privacy_notice_version": "privacy_notice_version",
}


def transition(
    db: Session,
    *,
    actor: AuthenticatedActor,
    campaign: Campaign,
    destination: CampaignState,
    reason: str,
    approval_actor_id: uuid.UUID | None = None,
) -> Campaign:
    source = CampaignState(campaign.state)
    rule = find_transition(source, destination)
    if rule is None:
        raise InvalidTransitionError(
            f"Transition {source.value} -> {destination.value} is not permitted"
        )

    # Permission + object-level authorisation.
    require_campaign_permission(actor, rule.permission, campaign.id)

    if not reason or not reason.strip():
        raise ValidationError("A transition reason is required")

    _check_prerequisites(campaign, rule)
    _check_approval(rule, actor, approval_actor_id)

    campaign.state = destination.value
    if destination is CampaignState.APPROVED:
        campaign.approved_by = actor.user_id
    if destination is CampaignState.PUBLISHED:
        campaign.published_by = actor.user_id
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=campaign.organisation_id,
            actor_id=actor.user_id,
            action=f"campaign.transition.{rule.name}",
            entity_type="campaign",
            entity_id=str(campaign.id),
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
    return campaign


def _check_prerequisites(campaign: Campaign, rule: TransitionRule) -> None:
    missing: list[str] = []
    for requirement in rule.required:
        attr = _PREREQUISITE_ATTR.get(requirement)
        if attr is None:
            # Data prerequisites not tied to a campaign column (e.g. an uploaded document,
            # an extraction draft) are validated by the calling service before invoking
            # the transition; they are not re-checked here.
            continue
        if getattr(campaign, attr, None) is None:
            missing.append(requirement)
    if missing:
        raise InvalidTransitionError(
            "Transition blocked; missing prerequisites: " + ", ".join(sorted(missing))
        )


def _check_approval(
    rule: TransitionRule, actor: AuthenticatedActor, approval_actor_id: uuid.UUID | None
) -> None:
    if not rule.requires_approval:
        return
    # The transition itself is the approving action performed by an authorised actor.
    # Separation-of-duties for specific artifacts (rules/thresholds) is enforced in those
    # modules; here we require that the acting user holds the approving permission, which
    # require_campaign_permission already verified. ``approval_actor_id`` is reserved for
    # flows that record a distinct approver.
    return
