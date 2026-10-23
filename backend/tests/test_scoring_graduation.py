"""Regression tests for the 0/100 scoring bug.

Root cause (now fixed): the dev "open campaign now" flow wired a hardcoded starter rule-set
whose only decidable criterion was a single mandatory experience gate. With just one
decidable criterion the weighted fit score could only ever be 0 (fail) or 100 (pass) — the
reported symptom. The fix makes the campaign screen against JD-derived TIERED SKILL +
experience criteria, so a candidate matching SOME of the skills scores somewhere strictly
between 0 and 100.

These tests prove:
  1. The synthetic dev JD text extracts into multiple tiered skills.
  2. The JD-derived rule builder turns those into several weighted skill criteria.
  3. A screening run with a PARTIAL skill match produces a graduated score (not 0, not 100).

All data is synthetic.
"""

from __future__ import annotations

import uuid

from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.dev.service import _SYNTHETIC_JD_TEXT
from app.modules.extraction.jd_extractor import extract_tiered_skills
from app.modules.extraction.models import ExtractedField, VerificationStatus
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.rules import service as rules_service
from app.modules.screening import service as screening_service
from tests.factories import make_org

CAMPAIGN = uuid.uuid4()


def _actor(org):  # type: ignore[no-untyped-def]
    return AuthenticatedActor(
        user_id=uuid.uuid4(), organisation_id=org.id, email="screener@example.com",
        role_names=["recruiter"],
        permissions={Permission.SCREENING_EXECUTE.value, Permission.APPLICATION_REVIEW.value},
        assigned_campaign_ids={CAMPAIGN},
    )


def test_synthetic_dev_jd_text_extracts_multiple_tiered_skills() -> None:
    """The dev synthetic JD must yield several skills across tiers (not a single criterion),
    otherwise the dev 'open now' flow reproduces the 0/100 bug it is meant to avoid."""
    tiered = extract_tiered_skills(_SYNTHETIC_JD_TEXT.decode())
    # Must-have skills present and correct.
    assert {"python", "sql"} <= {s.lower() for s in tiered["mandatory"]}
    # Good-to-have and nice-to-have tiers are populated too, so scoring can graduate.
    assert tiered["desirable"], tiered
    assert tiered["nice_to_have"], tiered
    total = len(tiered["mandatory"]) + len(tiered["desirable"]) + len(tiered["nice_to_have"])
    assert total >= 4, tiered


def test_jd_derived_rules_have_multiple_weighted_skill_criteria() -> None:
    tiered = extract_tiered_skills(_SYNTHETIC_JD_TEXT.decode())
    rules = rules_service.build_rules_from_jd(
        mandatory_skills=tiered["mandatory"],
        desirable_skills=tiered["desirable"],
        nice_to_have_skills=tiered["nice_to_have"],
        minimum_total_experience_years=1,
    )
    skill_rules = [r for r in rules if r["criterion_type"] == "exact_skill"]
    # Several weighted skill criteria -> the denominator has many decidable criteria, so the
    # score is no longer all-or-nothing.
    assert len(skill_rules) >= 4, rules
    # Mixed weights across tiers (must/good/nice) so matches of different tiers blend.
    weights = {r["weight"] for r in skill_rules}
    assert len(weights) >= 2, skill_rules


def _skill_field(org_id, app_id, skill):  # type: ignore[no-untyped-def]
    # The evaluator reads verified skills from fields named "skill:<id>" (see the screening
    # service's evidence builder). A VERIFIED skill field means the resume confirmed it.
    key = skill.lower()
    return ExtractedField(
        organisation_id=org_id, application_id=app_id, field_name=f"skill:{key}",
        extracted_value="present", verified_value="present",
        status=VerificationStatus.VERIFIED.value, extraction_method="manual", confidence=1.0,
    )


def test_partial_skill_match_produces_graduated_score(db_session) -> None:
    """A candidate who confirms SOME (not all, not none) of the JD skills must score strictly
    between 0 and 100 — the direct proof the 0/100 collapse is gone."""
    org = make_org(db_session)
    tiered = extract_tiered_skills(_SYNTHETIC_JD_TEXT.decode())
    rules = rules_service.build_rules_from_jd(
        mandatory_skills=tiered["mandatory"],
        desirable_skills=tiered["desirable"],
        nice_to_have_skills=tiered["nice_to_have"],
        minimum_total_experience_years=1,
    )
    version = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="jd-rs",
        rules=rules, actor_id=uuid.uuid4(),
    )
    version = rules_service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=version.id, approver_id=uuid.uuid4(),
    )
    threshold = rules_service.change_threshold(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN,
        review_below=50, recommend_at_or_above=70, change_reason="init",
        actor_id=uuid.uuid4(), approver_id=uuid.uuid4(),
    )

    app = Application(
        organisation_id=org.id, campaign_id=CAMPAIGN, candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(),
        answers={"total_experience_years": "5", "full_name": "Synthetic Candidate"},
        state=ApplicationState.EXTRACTION_REVIEW.value,
    )
    db_session.add(app)
    db_session.flush()

    # Confirm the two MUST-HAVE skills + one good-to-have, but NOT the rest. This is a
    # genuine partial match: mandatory criteria pass (so no mandatory-review gate), and some
    # optional skills are unconfirmed (earning 0 but staying in the denominator).
    all_optional = tiered["desirable"] + tiered["nice_to_have"]
    confirmed = list(tiered["mandatory"]) + all_optional[:1]
    for skill in confirmed:
        db_session.add(_skill_field(org.id, app.id, skill))
    db_session.flush()

    run = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=version, threshold_version=threshold, actor=_actor(org),
    ).run

    # The crux: NOT the degenerate 0 or 100.
    detail = [
        (r.criterion_name, r.outcome, r.awarded_score, r.max_score) for r in run.results
    ]
    assert 0.0 < run.score < 100.0, (
        f"expected a graduated score, got {run.score}; results={detail}"
    )
