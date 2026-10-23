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
from app.modules.job_descriptions.models import JDVersion
from app.modules.job_descriptions.schemas import JDVersionUpdate
from app.modules.rules import service as rules_service
from app.modules.rules.models import RuleSetVersion, ThresholdSet

# Synthetic JD text for the dev "open now" flow. Skills are listed on their OWN lines under
# tier sub-headers ("Must Have:" / "Good to Have:" / "Nice to Have:") because the JD
# extractor collects skills from the lines FOLLOWING a tier header, not from the header line
# itself. Multiple weighted skill criteria (not a single mandatory experience gate) are what
# make the resulting fit score graduate across 0..100 instead of collapsing to only 0 or 100.
_SYNTHETIC_JD_TEXT = (
    b"Position Title: Demo Role\n"
    b"Department: Engineering\n"
    b"\n"
    b"Responsibilities:\n"
    b"Build and ship features\n"
    b"Collaborate with the team\n"
    b"\n"
    b"Must Have:\n"
    b"Python\n"
    b"SQL\n"
    b"REST APIs\n"
    b"\n"
    b"Good to Have:\n"
    b"Docker\n"
    b"PostgreSQL\n"
    b"React\n"
    b"\n"
    b"Nice to Have:\n"
    b"Kubernetes\n"
    b"GraphQL\n"
    b"\n"
    b"Minimum Total Experience: 1 year\n"
)

# The same tiered skills the synthetic JD text encodes, as structured lists. Used to BACKFILL
# an existing approved JD that has no skills (e.g. a real JD whose document yielded none, or
# one approved before skill extraction), so the dev open-now flow can still build graduated
# scoring criteria. JDVersion carries two skill columns, so nice-to-have is merged into
# desirable (both are weighted, non-mandatory tiers in the rule generator).
_SYNTHETIC_MANDATORY_SKILLS = ["Python", "SQL", "REST APIs"]
_SYNTHETIC_DESIRABLE_SKILLS = ["Docker", "PostgreSQL", "React", "Kubernetes", "GraphQL"]
_SYNTHETIC_MIN_EXPERIENCE_YEARS = 1.0


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


def _ensure_skill_based_rules(
    db: Session, *, org: uuid.UUID, campaign: Campaign, approver_id: uuid.UUID
) -> None:
    """Guarantee the campaign is screened against JD-derived skill criteria.

    Normally ``approve_jd_version`` has already auto-generated and approved tiered skill +
    experience criteria from the JD. This is a dev-only safety net: if the approved rule set
    is still missing or contains no skill criteria (which collapses every fit score to 0 or
    100), regenerate fresh JD-derived criteria. Four-eyes is preserved by the rules service
    (a fixed system identity authors; a distinct human approves)."""
    needs_rules = campaign.approved_rule_set_version_id is None
    if not needs_rules:
        existing = db.get(RuleSetVersion, campaign.approved_rule_set_version_id)
        needs_rules = existing is None or not any(
            rules_service._contains_skill_criterion(rule)
            for rule in (existing.rules or [])
        )
    if needs_rules:
        rules_service.regenerate_criteria_from_jd(
            db, organisation_id=org, campaign_id=campaign.id, approver_id=approver_id
        )
        db.refresh(campaign)


def _backfill_skills_if_empty(
    db: Session, *, org: uuid.UUID, campaign: Campaign, actor_id: uuid.UUID
) -> None:
    """If the campaign's approved JD has no skills and no minimum experience, revise it into
    a new draft, backfill the synthetic tiered skills + minimum experience, and re-approve.

    This is the dev-only repair for a campaign whose approved JD yielded no scoring signal
    (a real JD document that extracted no skills, or one approved before extraction existed).
    Approved JD versions are immutable, so we clone via ``revise_jd_version`` (the original
    approved version is preserved), edit the draft, and re-approve — which re-points the
    campaign and triggers JD-derived criteria generation. No-op when the JD already has
    usable skills or experience."""
    jd = db.get(JDVersion, campaign.approved_jd_version_id)
    if jd is None:
        return
    has_signal = bool(jd.mandatory_skills or jd.desirable_skills) or (
        jd.minimum_total_experience_years is not None
        and jd.minimum_total_experience_years > 0
    )
    if has_signal:
        return

    draft = jd_service.revise_jd_version(
        db, organisation_id=org, approved_version_id=jd.id, actor_id=actor_id
    )
    jd_service.update_jd_version(
        db,
        organisation_id=org,
        jd_version_id=draft.id,
        actor_id=actor_id,
        data=JDVersionUpdate(
            mandatory_skills=list(_SYNTHETIC_MANDATORY_SKILLS),
            desirable_skills=list(_SYNTHETIC_DESIRABLE_SKILLS),
            minimum_total_experience_years=_SYNTHETIC_MIN_EXPERIENCE_YEARS,
        ),
    )
    jd_service.approve_jd_version(
        db,
        organisation_id=org,
        jd_version_id=draft.id,
        actor_id=actor_id,
        change_reason="dev autopilot: backfill synthetic skills for scoring",
    )
    db.refresh(campaign)


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
    else:
        # A JD is already approved. If it has NO skills and NO minimum experience, the dev
        # flow cannot build scoring criteria from it (the "approved JD lists no skills or
        # experience" error). This happens when a real JD document yielded no extractable
        # skills, or was approved before skill extraction existed. Approved JDs are
        # immutable, so we REVISE it into a new draft, backfill the synthetic tiered skills +
        # minimum experience, and re-approve — the original approved version is preserved.
        _backfill_skills_if_empty(db, org=org, campaign=campaign, actor_id=actor_id)

    # --- 2. Rule set: derived from the JUST-APPROVED JD's tiered skills + experience. ---
    # Approving the JD above already auto-generates and approves JD-derived scoring criteria
    # (tiered skill rules + experience) and points the campaign at them, so in the normal
    # path there is nothing to do here. We only step in if, for any reason, the campaign has
    # no approved rule set OR its approved set has no skill criteria (a stale/placeholder set
    # scores every candidate 0 or 100 because a single decidable criterion can only be all-
    # or-nothing). In that case we regenerate the JD-derived criteria so scores blend across
    # the full 0..100 range. Four-eyes is preserved (system identity authors, distinct human
    # approves) by regenerate_criteria_from_jd / auto_generate_criteria_on_jd_approval.
    _ensure_skill_based_rules(db, org=org, campaign=campaign, approver_id=approver_id)

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
    # JD approval already ensured a default 50/50 single-gate threshold. For the dev flow we
    # want a review band (review_below=50, recommend_at_or_above=70) so results spread across
    # "below / review / recommended" instead of a single pass/fail line. Always (re)apply the
    # dev band here rather than only when no threshold exists.
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
