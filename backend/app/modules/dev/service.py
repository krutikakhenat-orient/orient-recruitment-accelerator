"""DEV-ONLY orchestration: take a DRAFT campaign all the way to APPLICATIONS_OPEN.

This exists purely to make local evaluation easy. It creates and approves all five
governed artifacts (JD, rule-set, form, threshold, privacy notice), wires them to the
campaign, and drives every lifecycle transition in a single server-side call.

It must NEVER be reachable in a production-like environment (the router gates on
``settings.is_production_like``). It also relaxes the thresholds four-eyes requirement for
the target campaign (dev convenience only) and, when no second staff user exists, performs
the rule-set approval with a synthesized distinct approver id so separation-of-duties still
holds structurally.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.campaigns import service as campaign_service
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.campaigns.transition_service import transition
from app.modules.forms import service as forms_service
from app.modules.identity.models import User
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.job_descriptions import service as jd_service
from app.modules.job_descriptions.schemas import JDVersionUpdate
from app.modules.rules import service as rules_service
from app.modules.rules.models import ThresholdSet

# A minimal, DSL-valid rule set (mirrors the frontend "starter" rules).
_STARTER_RULES: list[dict[str, object]] = [
    {
        "rule_id": "R-TOTAL-EXP",
        "name": "Minimum total experience",
        "criterion_type": "numeric_comparison",
        "field": "total_experience_years",
        "operator": "gte",
        "expected_value": 1,
        "weight": 40,
        "mandatory": True,
        "missing_evidence": "manual_review",
    },
    {
        "rule_id": "R-NOTICE",
        "name": "Notice period acceptable",
        "criterion_type": "numeric_comparison",
        "field": "notice_period_days",
        "operator": "lte",
        "expected_value": 90,
        "weight": 20,
        "mandatory": False,
        "missing_evidence": "manual_review",
    },
]

_SYNTHETIC_JD_TEXT = (
    b"Position Title: Demo Role\n"
    b"Department: Engineering\n"
    b"Responsibilities: Build and ship features; collaborate with the team.\n"
    b"Mandatory Skills: Python, SQL\n"
    b"Minimum Total Experience: 1 year\n"
)


def _dev_actor(campaign: Campaign) -> AuthenticatedActor:
    """A full-permission actor assigned to the campaign (dev-only)."""
    return AuthenticatedActor(
        user_id=campaign.created_by or uuid.uuid4(),
        organisation_id=campaign.organisation_id,
        email="dev.autopilot@example.com",
        role_names=["dev_autopilot"],
        permissions={p.value for p in Permission},
        assigned_campaign_ids={campaign.id},
    )


def _find_distinct_approver(db: Session, org_id: uuid.UUID, exclude: uuid.UUID) -> uuid.UUID:
    """Return another staff user's id to satisfy four-eyes; synthesize one if none exists."""
    stmt = (
        select(User.id)
        .where(User.organisation_id == org_id, User.id != exclude)
        .limit(1)
    )
    other = db.execute(stmt).scalars().first()
    return other if other is not None else uuid.uuid4()


def open_campaign_now(
    db: Session, *, campaign: Campaign, caller_user_id: uuid.UUID | None = None
) -> Campaign:
    """Drive a DRAFT campaign to APPLICATIONS_OPEN, creating all artifacts along the way.

    If ``caller_user_id`` is provided, that user is also assigned to the campaign so they
    can immediately use the authoring tabs without the "not assigned" error.
    """
    actor = _dev_actor(campaign)
    actor_id = actor.user_id
    org = campaign.organisation_id
    approver_id = _find_distinct_approver(db, org, actor_id)

    # Assign the human caller so the campaign isn't locked to its original creator.
    if caller_user_id is not None:
        campaign_service.assign_user(
            db,
            organisation_id=org,
            campaign=campaign,
            user_id=caller_user_id,
            actor_id=actor_id,
        )

    # Idempotency: if already open (or beyond), do nothing.
    current = CampaignState(campaign.state)
    if current in {
        CampaignState.APPLICATIONS_OPEN,
        CampaignState.APPLICATIONS_CLOSED,
        CampaignState.SCREENING,
    }:
        return campaign

    # --- 1. Job description: create (synthetic .txt), ensure title, approve, wire. ---
    if campaign.approved_jd_version_id is None:
        jd = jd_service.upload_jd(
            db,
            organisation_id=org,
            campaign_id=campaign.id,
            actor_id=actor_id,
            filename="jd.txt",
            declared_content_type="text/plain",
            data=_SYNTHETIC_JD_TEXT,
        )
        if not jd.position_title:
            jd = jd_service.update_jd_version(
                db,
                organisation_id=org,
                jd_version_id=jd.id,
                actor_id=actor_id,
                data=JDVersionUpdate(position_title=campaign.position_title or "Demo Role"),
            )
        jd = jd_service.approve_jd_version(
            db,
            organisation_id=org,
            jd_version_id=jd.id,
            actor_id=actor_id,
            change_reason="dev autopilot",
        )
        campaign_service.set_approved_jd_version(db, campaign, jd.id, actor_id)

    # --- 2. Rule set: create as actor, approve as a DISTINCT user (four-eyes), wire. ---
    if campaign.approved_rule_set_version_id is None:
        rsv = rules_service.create_rule_set_version(
            db,
            organisation_id=org,
            campaign_id=campaign.id,
            name="Dev autopilot rule set",
            rules=_STARTER_RULES,
            actor_id=actor_id,
        )
        rsv = rules_service.approve_rule_set_version(
            db, organisation_id=org, version_id=rsv.id, approver_id=approver_id
        )
        campaign_service.configure_governance(
            db, campaign, actor_id=actor_id, approved_rule_set_version_id=rsv.id
        )

    # --- 3. Form: create baseline draft, approve, wire. ---
    if campaign.approved_form_version_id is None:
        fv = forms_service.create_form_draft(
            db, organisation_id=org, campaign_id=campaign.id, actor_id=actor_id
        )
        fv = forms_service.approve_form_version(
            db, organisation_id=org, form_version_id=fv.id, actor_id=actor_id
        )
        campaign_service.set_approved_form_version(db, campaign, fv.id, actor_id)

    # --- 4. Threshold: relax four-eyes for this campaign (dev), create+approve, wire. ---
    if campaign.active_threshold_version_id is None:
        ts = db.execute(
            select(ThresholdSet).where(
                ThresholdSet.organisation_id == org,
                ThresholdSet.campaign_id == campaign.id,
            )
        ).scalars().first()
        if ts is None:
            ts = ThresholdSet(organisation_id=org, campaign_id=campaign.id)
            db.add(ts)
        ts.four_eyes_required = False  # dev-only relaxation
        db.flush()
        tv = rules_service.change_threshold(
            db,
            organisation_id=org,
            campaign_id=campaign.id,
            review_below=50,
            recommend_at_or_above=70,
            change_reason="dev autopilot",
            actor_id=actor_id,
            approver_id=actor_id,
        )
        campaign_service.configure_governance(
            db, campaign, actor_id=actor_id, active_threshold_version_id=tv.id
        )

    # --- 5. Privacy notice: any non-null string. ---
    if campaign.privacy_notice_version is None:
        campaign_service.configure_governance(
            db, campaign, actor_id=actor_id, privacy_notice_version="dev-v1"
        )

    # --- 6. Drive the lifecycle to APPLICATIONS_OPEN (only the needed forward steps). ---
    path = [
        CampaignState.JD_UPLOADED,
        CampaignState.JD_REVIEW,
        CampaignState.CRITERIA_CONFIGURATION,
        CampaignState.CRITERIA_REVIEW,
        CampaignState.APPROVAL_PENDING,
        CampaignState.APPROVED,
        CampaignState.PUBLISHED,
        CampaignState.APPLICATIONS_OPEN,
    ]
    order = {s: i for i, s in enumerate(path)}
    start_index = order.get(CampaignState(campaign.state), 0)
    # If we're still in DRAFT, start from the very first step.
    if CampaignState(campaign.state) is CampaignState.DRAFT:
        start_index = 0
    for destination in path[start_index:]:
        if CampaignState(campaign.state) is destination:
            continue
        transition(
            db,
            actor=actor,
            campaign=campaign,
            destination=destination,
            reason="dev autopilot: open campaign",
        )

    db.commit()
    db.refresh(campaign)
    return campaign
