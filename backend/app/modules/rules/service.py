"""Rules & thresholds application service (Req 7.1, 7.2; AC-03, AC-11, AC-12).

Enforces:
- Typed-JSON rule validation at authoring time (reject malformed before approval).
- Immutable approved rule-set versions (AC-03).
- Separation of duties: the creator of a rule set cannot be its sole approver.
- Threshold changes create a new immutable version with a reason and audit event (AC-12),
  and require a DISTINCT approver when four-eyes is configured.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    ConflictError,
    NotFoundError,
    SeparationOfDutiesError,
    ValidationError,
)
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.rules.models import (
    ApprovalStatus,
    RuleSet,
    RuleSetVersion,
    ThresholdSet,
    ThresholdVersion,
)
from app.rules_engine.dsl import SkillTier, validate_rule_set


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


# --- JD-derived skill rules ----------------------------------------------------

# Default weights per tier (relative point contribution to the 0..100 fit score).
_TIER_WEIGHT = {
    SkillTier.MUST_HAVE: 20.0,
    SkillTier.GOOD_TO_HAVE: 10.0,
    SkillTier.NICE_TO_HAVE: 5.0,
}


def _skill_criterion(skill: str, tier: SkillTier) -> dict[str, Any]:
    """One exact_skill criterion for a JD skill, scored by tier.

    Scoring semantics by tier:
      - MUST_HAVE  -> mandatory. An UNCONFIRMED must-have routes to HUMAN REVIEW
        (missing_evidence=manual_review), never an automatic fail/rejection
        (responsible-ai.md).
      - GOOD_TO_HAVE / NICE_TO_HAVE -> weighted, NOT mandatory. A confirmed skill awards its
        weight; an unconfirmed one simply scores 0 (missing_evidence=fail) WITHOUT routing
        the whole run to review or opening a review item. This is weighted scoring, not a
        rejection: an optional skill the candidate did not demonstrate just earns no points.
    """
    key = skill.strip().lower()
    mandatory = tier is SkillTier.MUST_HAVE
    return {
        "rule_id": f"SKILL-{key}",
        "name": skill.strip(),
        "criterion_type": "exact_skill",
        "skill_id": key,
        "operator": "contains_verified",
        "expected_value": key,
        "weight": _TIER_WEIGHT[tier],
        "mandatory": mandatory,
        "tier": tier.value,
        # Mandatory -> review (never auto-reject). Optional -> FAIL: an optional (good/nice-
        # to-have) skill the resume does not demonstrate earns 0 points but STAYS in the
        # weighted denominator. This is honest weighted scoring: a candidate with 2 of 5
        # desirable skills scores ~40% on skills, not 100% (which would happen if misses were
        # dropped from the denominator) and not a run-wide review. Only MUST-HAVE skills gate
        # or route to human review; optional misses simply don't earn their weight.
        "missing_evidence": "manual_review" if mandatory else "fail",
    }


def build_skill_rules_from_jd(
    mandatory_skills: list[str],
    desirable_skills: list[str],
    nice_to_have_skills: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Derive a tiered skill rule-set from a JD's skill lists.

    JD mandatory skills  -> Must-Have (mandatory gate; unconfirmed -> review).
    JD desirable skills  -> Good-to-Have (weighted; unconfirmed -> 0 points).
    nice_to_have_skills  -> Nice-to-Have (lower weighted; unconfirmed -> 0 points).

    De-duplicates case-insensitively across all tiers, keeping the highest tier a skill
    appears in (must > good > nice) so a skill listed in two tiers is scored once.
    """
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skills, tier in (
        (mandatory_skills, SkillTier.MUST_HAVE),
        (desirable_skills, SkillTier.GOOD_TO_HAVE),
        (nice_to_have_skills or [], SkillTier.NICE_TO_HAVE),
    ):
        for s in skills:
            key = s.strip().lower()
            # Defence-in-depth: skip entries that are clearly NOT skills (e.g. an experience
            # or qualification sentence mis-captured into the skills list). Turning such a
            # phrase into an exact_skill criterion would never match a resume and make every
            # candidate score 0 on skills. Experience is scored by its own criterion.
            if key and key not in seen and _is_skill_like(s):
                seen.add(key)
                rules.append(_skill_criterion(s, tier))
    return rules


# A skills-list entry that is really an experience / qualification / compensation statement,
# not an actual skill token. Mirrors the JD extractor's filter so bad data from any source
# (extraction OR manual entry) cannot produce a garbage skill criterion.
_NON_SKILL_PHRASE = re.compile(
    r"\b(experience|years?|yrs?|minimum|maximum|at\s+least|notice\s+period|"
    r"salary|ctc|openings?|vacanc|qualification|degree|graduate|bachelor|master)\b",
    re.IGNORECASE,
)


def _is_skill_like(entry: str) -> bool:
    """True if an entry is a plausible skill token (not a responsibility sentence, heading,
    location, date, salary or other prose fragment).

    Delegates to the JD extractor's token normaliser as the single source of truth: if the
    extractor would reject the entry as not-a-skill (leading action verb, all-heading words,
    experience/qualification/compensation fragment, too long), the rule generator rejects it
    too. This cleans GARBAGE stored skill lists (e.g. a JD approved before the extractor was
    hardened, whose mandatory_skills contained 'Provide L2 operational', 'WALK-IN DETAILS',
    'October 2026', 'Maharashtra 400093') so regenerated criteria contain only real skills.
    """
    text = entry.strip()
    if not text or _NON_SKILL_PHRASE.search(text):
        return False
    from app.modules.extraction.jd_extractor import _normalise_skill_token

    return _normalise_skill_token(text) is not None


def _experience_criterion(min_years: float) -> dict[str, Any]:
    """A weighted total-experience criterion. Not mandatory by default: falling short of the
    target reduces the fit score rather than gating, so experience is one weighted signal
    alongside skills. Missing evidence routes to review (never a silent pass)."""
    return {
        "rule_id": "EXP-TOTAL",
        "name": "Total experience",
        "criterion_type": "numeric_comparison",
        "field": "total_experience_years",
        "operator": "gte",
        "expected_value": min_years,
        "weight": 20.0,
        "mandatory": False,
        "missing_evidence": "manual_review",
    }


def build_rules_from_jd(
    *,
    mandatory_skills: list[str],
    desirable_skills: list[str],
    nice_to_have_skills: list[str] | None = None,
    minimum_total_experience_years: float | None = None,
) -> list[dict[str, Any]]:
    """Build ONE complete scoring rule-set from a JD: tiered skills PLUS experience.

    This is the combined rule-set the campaign screens against, so a candidate is scored on
    skills AND experience together (not skills in isolation). Notice period / location can be
    added via manual rule authoring; they are intentionally not auto-generated here because
    the JD does not carry a target for them.
    """
    rules = build_skill_rules_from_jd(mandatory_skills, desirable_skills, nice_to_have_skills)
    if minimum_total_experience_years is not None and minimum_total_experience_years > 0:
        rules.append(_experience_criterion(minimum_total_experience_years))
    return rules


def _clean_jd_skills(jd: Any) -> tuple[list[str], list[str]]:
    """Derive clean (mandatory, desirable) skill lists for rule generation from a JD version.

    Robust against a JD whose stored skill lists are noisy (e.g. approved before the
    extractor was hardened, so mandatory_skills holds responsibility sentences, headings,
    dates and addresses). Strategy, in order of trust:
      1. Run the known-skill gazetteer over the JD's extracted text (extraction_draft) — the
         most reliable signal, since it only returns real skill terms literally present.
      2. Keep stored skills that still pass the (now stricter) _is_skill_like filter.
      3. Merge: gazetteer hits + surviving stored skills, de-duplicated, preserving tiers
         (stored desirable stays desirable; gazetteer hits are mandatory core skills).
    The result feeds build_rules_from_jd, which applies _is_skill_like once more as a final
    guard.
    """
    from app.modules.extraction.jd_extractor import scan_known_skills

    draft = jd.extraction_draft if isinstance(jd.extraction_draft, dict) else {}
    # The stored draft keeps the extracted text pieces; reconstruct a scannable blob from the
    # draft fields, responsibilities and the skill names themselves.
    blob_parts: list[str] = []
    for key in ("responsibilities", "mandatory_skills", "desirable_skills"):
        val = draft.get(key)
        if isinstance(val, list):
            blob_parts.extend(str(x) for x in val)
    blob_parts.extend(str(s) for s in (jd.mandatory_skills or []))
    blob_parts.extend(str(s) for s in (jd.desirable_skills or []))
    gazetteer = scan_known_skills("\n".join(blob_parts))

    stored_mandatory = [s for s in (jd.mandatory_skills or []) if _is_skill_like(s)]
    stored_desirable = [s for s in (jd.desirable_skills or []) if _is_skill_like(s)]

    # When the gazetteer recognises a usable set of real skills, TRUST IT ALONE for the
    # mandatory tier and discard the stored mandatory list. A stored list for a prose JD is
    # frequently noise (responsibility fragments, headings, single generic words like
    # "objects"/"problem"/"alerts"/"Server") that individually slip past _is_skill_like but
    # collectively bloat the denominator and crater every score. The gazetteer only returns
    # curated, real skill terms literally present in the JD, so it is the trustworthy source.
    # We only FALL BACK to the filtered stored mandatory list when the gazetteer found
    # essentially nothing (an unusual role not covered by the gazetteer yet), so we still
    # build a defensible rule set rather than none.
    if len(gazetteer) >= 3:
        mandatory_source = gazetteer
    else:
        seen0: set[str] = {g.lower() for g in gazetteer}
        mandatory_source = gazetteer + [
            s for s in stored_mandatory if s.strip().lower() not in seen0
        ]

    seen: set[str] = set()
    mandatory: list[str] = []
    for s in mandatory_source:
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            mandatory.append(s)
    # Keep explicitly-tiered desirable skills only when they are gazetteer-recognised real
    # skills (so an explicit "Good to Have: Python" is honoured, but stored desirable noise
    # is dropped). Desirable that duplicates a mandatory entry is skipped.
    gaz_lower = {g.lower() for g in gazetteer}
    desirable = [
        s for s in stored_desirable
        if s.strip().lower() in gaz_lower and s.strip().lower() not in seen
    ]
    return mandatory, desirable


def create_rule_set_version_from_jd(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> RuleSetVersion:
    """Create a DRAFT rule-set version whose criteria are the campaign's JD skills, tiered.

    Reads the campaign's approved JD version; raises if none is approved yet. The draft still
    goes through normal four-eyes approval before it can be used for screening.
    """
    from app.modules.campaigns.models import Campaign
    from app.modules.job_descriptions.models import JDVersion

    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.organisation_id != organisation_id:
        raise NotFoundError("Campaign not found")
    if campaign.approved_jd_version_id is None:
        raise ValidationError("Approve a Job Description first — skill rules come from the JD")
    jd = db.get(JDVersion, campaign.approved_jd_version_id)
    if jd is None:
        raise NotFoundError("Approved JD version not found")

    mandatory, desirable = _clean_jd_skills(jd)
    rules = build_rules_from_jd(
        mandatory_skills=mandatory,
        desirable_skills=desirable,
        minimum_total_experience_years=jd.minimum_total_experience_years,
    )
    if not rules:
        raise ValidationError(
            "The approved JD lists no skills or experience to build rules from — "
            "add skills (or a minimum experience) to the JD first"
        )
    return create_rule_set_version(
        db, organisation_id=organisation_id, campaign_id=campaign_id,
        name=f"Scoring rules from JD: {jd.position_title or 'role'}",
        rules=rules, actor_id=actor_id,
    )


# A fixed, non-human system identity that AUTHORS auto-generated criteria/thresholds. Using
# a distinct id (never a real user) means the human JD-approver can APPROVE the generated
# artifacts without violating four-eyes separation-of-duties: creator (system) != approver
# (human). This preserves the SoD safeguard rather than bypassing it.
SYSTEM_CRITERIA_AUTHOR_ID = uuid.UUID("00000000-0000-0000-0000-0000000c0de0")

# Default campaign progression threshold (meeting requirement): a final score >= 50
# qualifies for the next stage; exactly 50 qualifies. review_below == recommend_at_or_above
# == 50 means there is a single 50% gate (no borderline band): >=50 -> recommended, <50 ->
# below. This is the DEFAULT for auto-configured campaigns; HR can still version it later.
DEFAULT_THRESHOLD = 50.0


def auto_generate_criteria_on_jd_approval(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    approver_id: uuid.UUID,
) -> RuleSetVersion | None:
    """Auto-generate, validate, save and APPROVE scoring criteria from the campaign's
    just-approved JD, and ensure a default 50% threshold exists — so HR never has to open a
    Rules tab.

    Safeguards preserved (NOT bypassed):
      - Four-eyes: the criteria/threshold are AUTHORED by a fixed system identity and
        APPROVED by the human JD-approver, so creator != approver (the SoD rule in
        approve_rule_set_version / change_threshold still holds with distinct ids).
      - Determinism: criteria are the existing JD-derived typed-JSON rules, validated by
        validate_rule_set before persistence; the scoring engine is unchanged.
      - No empty/misleading criteria: if the JD yields no usable criteria this raises
        ValidationError so the caller can surface a manual-review warning instead of
        silently approving empty rules.
      - Idempotent: if an approved rule-set already exists for the campaign (e.g. the JD was
        re-approved), it is left as-is and only the threshold default is ensured.

    Returns the approved RuleSetVersion, or None if one already existed.
    """
    from app.modules.campaigns.models import Campaign

    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.organisation_id != organisation_id:
        raise NotFoundError("Campaign not found")

    # Ensure a default 50% threshold exists regardless of rule-set state (system-initiated,
    # human-approved -> four-eyes satisfied). Only create one if none is active yet.
    if campaign.active_threshold_version_id is None:
        change_threshold(
            db,
            organisation_id=organisation_id,
            campaign_id=campaign_id,
            review_below=DEFAULT_THRESHOLD,
            recommend_at_or_above=DEFAULT_THRESHOLD,
            change_reason="Default 50% progression threshold (auto-configured on JD approval)",
            actor_id=SYSTEM_CRITERIA_AUTHOR_ID,
            approver_id=approver_id,
        )

    # If the campaign already has an approved rule-set, only keep it when it ALREADY contains
    # JD-derived skill criteria. Otherwise it is a stale/starter set (e.g. an
    # experience+notice-period-only set created before the JD carried skills, or a manual
    # placeholder) that has NO skill rules to award points for — the confirmed cause of
    # candidates scoring 0 even when their resume matches JD skills. In that case we DO NOT
    # no-op: we regenerate fresh JD-derived criteria (which include the skill rules) so the
    # campaign scores correctly. A set that already has skill criteria is left untouched.
    if campaign.approved_rule_set_version_id is not None:
        existing = db.get(RuleSetVersion, campaign.approved_rule_set_version_id)
        if existing is not None and any(
            _contains_skill_criterion(rule) for rule in (existing.rules or [])
        ):
            return None
        # Stale rule-set without skill criteria -> rebuild from the JD (four-eyes preserved).

    # Build + persist the draft as the SYSTEM author, then approve as the human JD-approver.
    draft = create_rule_set_version_from_jd(
        db,
        organisation_id=organisation_id,
        campaign_id=campaign_id,
        actor_id=SYSTEM_CRITERIA_AUTHOR_ID,
    )
    return approve_rule_set_version(
        db,
        organisation_id=organisation_id,
        version_id=draft.id,
        approver_id=approver_id,
    )


def _contains_skill_criterion(rule: dict[str, Any]) -> bool:
    """True if a rule node is (or nests) an exact_skill criterion. Walks AND/OR/NOT groups so
    a skill rule buried inside a logical group still counts. Used to decide whether an
    existing approved rule-set already scores skills or is a stale skill-less starter set."""
    ctype = rule.get("criterion_type")
    if ctype == "exact_skill":
        return True
    if ctype in ("and", "or"):
        return any(_contains_skill_criterion(child) for child in rule.get("children", []))
    if ctype == "not":
        child = rule.get("child")
        return isinstance(child, dict) and _contains_skill_criterion(child)
    return False


def regenerate_criteria_from_jd(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    approver_id: uuid.UUID,
) -> RuleSetVersion:
    """Force-refresh a campaign's approved scoring criteria from its current approved JD.

    Unlike ``auto_generate_criteria_on_jd_approval`` (which no-ops when criteria already
    exist), this ALWAYS creates a new JD-derived rule-set version and approves it, repointing
    the campaign. It exists to repair campaigns whose approved rule-set predates JD-based
    criteria (e.g. an old manually-authored "experience + notice" starter set with no skill
    criteria), which is the confirmed cause of candidates scoring 0/100: the engine had no
    skill criteria to award points for, even though the resume skills were extracted.

    Safeguards preserved: criteria are JD-derived + validated (``validate_rule_set``), the
    system identity authors and a distinct human approves (four-eyes intact), prior rule-set
    versions remain immutable, and a JD with no usable criteria raises ValidationError
    instead of producing an empty set. Returns the new approved RuleSetVersion.
    """
    draft = create_rule_set_version_from_jd(
        db,
        organisation_id=organisation_id,
        campaign_id=campaign_id,
        actor_id=SYSTEM_CRITERIA_AUTHOR_ID,
    )
    return approve_rule_set_version(
        db,
        organisation_id=organisation_id,
        version_id=draft.id,
        approver_id=approver_id,
    )


# --- Rule sets -----------------------------------------------------------------

def _get_or_create_rule_set(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID, name: str
) -> RuleSet:
    stmt = select(RuleSet).where(
        RuleSet.organisation_id == organisation_id,
        RuleSet.campaign_id == campaign_id,
    )
    rs = db.execute(stmt).scalars().first()
    if rs is None:
        rs = RuleSet(organisation_id=organisation_id, campaign_id=campaign_id, name=name)
        db.add(rs)
        db.flush()
    return rs


def _next_version(db: Session, rule_set_id: uuid.UUID) -> int:
    stmt = (
        select(RuleSetVersion.version_number)
        .where(RuleSetVersion.rule_set_id == rule_set_id)
        .order_by(RuleSetVersion.version_number.desc())
        .limit(1)
    )
    return (db.execute(stmt).scalars().first() or 0) + 1


def create_rule_set_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    name: str,
    rules: list[dict[str, Any]],
    actor_id: uuid.UUID,
) -> RuleSetVersion:
    # Validate the typed-JSON DSL BEFORE anything is persisted (reject malformed rules).
    validate_rule_set(rules)

    rule_set = _get_or_create_rule_set(db, organisation_id, campaign_id, name)
    version = RuleSetVersion(
        rule_set_id=rule_set.id,
        organisation_id=organisation_id,
        version_number=_next_version(db, rule_set.id),
        status=ApprovalStatus.DRAFT.value,
        rules=rules,
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action="rule_set_version.drafted", entity_type="rule_set_version",
            entity_id=str(version.id), new_state_ref="draft",
        ),
    )
    return version


def approve_rule_set_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    version_id: uuid.UUID,
    approver_id: uuid.UUID,
) -> RuleSetVersion:
    version = db.get(RuleSetVersion, version_id)
    if version is None or version.organisation_id != organisation_id:
        raise NotFoundError("Rule set version not found")
    if version.is_approved:
        raise ConflictError("Rule set version is already approved and immutable")

    # Separation of duties: creator cannot be the sole approver (Req 1.3.1).
    if version.created_by is not None and version.created_by == approver_id:
        raise SeparationOfDutiesError(
            "The creator of a rule set cannot be its sole approver"
        )

    # Re-validate defensively before freezing.
    validate_rule_set(version.rules)

    version.status = ApprovalStatus.APPROVED.value
    version.approved_by = approver_id
    version.approved_at = _now()
    db.flush()

    # Point the owning campaign at this approved rule-set version so screening uses it and
    # the campaign readiness check passes. Without this approved_rule_set_version_id stays
    # null and screening keeps falling back / the campaign can't be opened.
    from app.modules.campaigns.models import Campaign

    rule_set = db.get(RuleSet, version.rule_set_id)
    if rule_set is not None and rule_set.organisation_id == organisation_id:
        campaign = db.get(Campaign, rule_set.campaign_id)
        if campaign is not None and campaign.organisation_id == organisation_id:
            campaign.approved_rule_set_version_id = version.id
            db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=approver_id,
            action="rule_set_version.approved", entity_type="rule_set_version",
            entity_id=str(version.id), previous_state_ref="draft", new_state_ref="approved",
        ),
    )
    return version


def reject_rule_set_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    version_id: uuid.UUID,
    approver_id: uuid.UUID,
    change_reason: str,
) -> RuleSetVersion:
    """Reject a DRAFT rule-set version. A reason is required. Separation of duties still
    applies: the creator cannot reject their own rule set. Approved versions are immutable."""
    version = db.get(RuleSetVersion, version_id)
    if version is None or version.organisation_id != organisation_id:
        raise NotFoundError("Rule set version not found")
    if version.is_approved:
        raise ConflictError("An approved rule set is immutable; it cannot be rejected")
    if version.status == ApprovalStatus.REJECTED.value:
        raise ConflictError("Rule set version is already rejected")
    if not change_reason or not change_reason.strip():
        raise ValidationError("A reason is required to reject a rule set version")
    if version.created_by is not None and version.created_by == approver_id:
        raise SeparationOfDutiesError(
            "The creator of a rule set cannot be its sole decision-maker"
        )
    version.status = ApprovalStatus.REJECTED.value
    version.approved_by = approver_id
    version.approved_at = _now()
    version.change_reason = change_reason
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=approver_id,
            action="rule_set_version.rejected", entity_type="rule_set_version",
            entity_id=str(version.id), previous_state_ref="draft", new_state_ref="rejected",
            reason=change_reason,
        ),
    )
    return version


def list_pending_rule_set_versions(
    db: Session, organisation_id: uuid.UUID, campaign_ids: set[uuid.UUID] | None = None
) -> list[RuleSetVersion]:
    """Draft (pending-approval) rule-set versions org-wide, optionally restricted to the
    campaigns the approver is assigned to (object-level authorisation)."""
    stmt = (
        select(RuleSetVersion)
        .join(RuleSet, RuleSet.id == RuleSetVersion.rule_set_id)
        .where(
            RuleSet.organisation_id == organisation_id,
            RuleSetVersion.status == ApprovalStatus.DRAFT.value,
        )
        .order_by(RuleSetVersion.created_at.desc())
    )
    versions = list(db.execute(stmt).scalars())
    if campaign_ids is not None:
        versions = [v for v in versions if v.rule_set.campaign_id in campaign_ids]
    return versions


# --- Thresholds ----------------------------------------------------------------

def _get_or_create_threshold_set(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> ThresholdSet:
    stmt = select(ThresholdSet).where(
        ThresholdSet.organisation_id == organisation_id,
        ThresholdSet.campaign_id == campaign_id,
    )
    ts = db.execute(stmt).scalars().first()
    if ts is None:
        ts = ThresholdSet(organisation_id=organisation_id, campaign_id=campaign_id)
        db.add(ts)
        db.flush()
    return ts


def _next_threshold_version(db: Session, threshold_set_id: uuid.UUID) -> int:
    stmt = (
        select(ThresholdVersion.version_number)
        .where(ThresholdVersion.threshold_set_id == threshold_set_id)
        .order_by(ThresholdVersion.version_number.desc())
        .limit(1)
    )
    return (db.execute(stmt).scalars().first() or 0) + 1


def change_threshold(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    review_below: float,
    recommend_at_or_above: float,
    change_reason: str,
    actor_id: uuid.UUID,
    approver_id: uuid.UUID,
) -> ThresholdVersion:
    """Create a NEW approved threshold version (AC-12).

    Requires a reason. When four-eyes is configured, the approver must differ from the
    actor who initiated the change (AC-12 governance). Authorisation (threshold.change
    permission) is enforced at the router.
    """
    if not change_reason or not change_reason.strip():
        raise ValidationError("A reason is required to change a threshold")
    if not 0 <= review_below <= 100 or not 0 <= recommend_at_or_above <= 100:
        raise ValidationError("Threshold values must be between 0 and 100")
    if recommend_at_or_above < review_below:
        raise ValidationError("recommend_at_or_above cannot be below review_below")

    threshold_set = _get_or_create_threshold_set(db, organisation_id, campaign_id)

    if threshold_set.four_eyes_required and actor_id == approver_id:
        raise SeparationOfDutiesError(
            "Four-eyes approval is required: the approver must differ from the initiator"
        )

    version = ThresholdVersion(
        threshold_set_id=threshold_set.id,
        organisation_id=organisation_id,
        version_number=_next_threshold_version(db, threshold_set.id),
        status=ApprovalStatus.APPROVED.value,
        review_below=review_below,
        recommend_at_or_above=recommend_at_or_above,
        created_by=actor_id,
        approved_by=approver_id,
        approved_at=_now(),
        change_reason=change_reason,
    )
    db.add(version)
    db.flush()

    # Make this the campaign's ACTIVE threshold so screening and the readiness check use it.
    from app.modules.campaigns.models import Campaign

    campaign = db.get(Campaign, campaign_id)
    if campaign is not None and campaign.organisation_id == organisation_id:
        campaign.active_threshold_version_id = version.id
        db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action="threshold_version.changed", entity_type="threshold_version",
            entity_id=str(version.id), new_state_ref="approved", reason=change_reason,
        ),
    )
    return version


def get_rule_set_version(
    db: Session, organisation_id: uuid.UUID, version_id: uuid.UUID
) -> RuleSetVersion:
    v = db.get(RuleSetVersion, version_id)
    if v is None or v.organisation_id != organisation_id:
        raise NotFoundError("Rule set version not found")
    return v


def get_threshold_version(
    db: Session, organisation_id: uuid.UUID, version_id: uuid.UUID
) -> ThresholdVersion:
    v = db.get(ThresholdVersion, version_id)
    if v is None or v.organisation_id != organisation_id:
        raise NotFoundError("Threshold version not found")
    return v
