"""Case-insensitive, alias- and version-aware skill screening (Req 8.1-8.3).

Covers the "candidate scores 0 despite having the skill" class of bugs:
  - capitalisation mismatch ("Python" vs rule "python"),
  - versioned skills ("Python 3.10" / "PostgreSQL 15" resolving to the base skill),
  - unverified/available evidence being evaluated cleanly (and routing to review rather
    than silently failing to 0).

These are pure, deterministic unit tests of the matcher + alias taxonomy + evaluator; no
DB. Behaviour that is intentionally conservative per responsible-ai.md (an UNCONFIRMED
mandatory skill routes to human review, never auto-passes or auto-rejects) is asserted
explicitly so a future change cannot quietly weaken it.
"""

from __future__ import annotations

from app.modules.extraction.resume_extractor import match_skills_detailed, match_skills_in_text
from app.modules.extraction.skill_alias import expand_skill_terms, strip_version_suffix
from app.rules_engine.evaluator import (
    EvidenceSet,
    Outcome,
    evaluate_leaf,
)

RESUME = (
    "Senior Engineer. Built services in Python and FastAPI backed by PostgreSQL. "
    "Containerised with Docker. 6 years of experience.\n"
)


# --- (a) Capitalised resume skills match lowercase rule skills --------------------------


def test_capitalised_resume_skills_match_lowercase_rules() -> None:
    # Rule asks for lowercase canonical ids; resume uses capitalised / mixed case.
    result = match_skills_in_text(RESUME, ["python", "postgresql", "docker"])
    assert result == {"python": True, "postgresql": True, "docker": True}


def test_exact_skill_criterion_is_case_insensitive_in_evaluator() -> None:
    # The verified-skill pool is matched case-insensitively against the rule's expected id.
    evidence = EvidenceSet(verified_skills={"Python", "PostgreSQL"})
    node = {
        "criterion_type": "exact_skill", "name": "Python", "skill_id": "python",
        "operator": "contains_verified", "expected_value": "python",
        "weight": 40, "mandatory": True, "missing_evidence": "manual_review",
    }
    outcome = evaluate_leaf(node, evidence)
    assert outcome.outcome is Outcome.PASS
    assert outcome.awarded_score == 40


# --- (b) Versioned skills resolve to the base skill -------------------------------------


def test_version_suffix_is_stripped() -> None:
    assert strip_version_suffix("Python 3.10") == "Python"
    assert strip_version_suffix("PostgreSQL 15") == "PostgreSQL"
    assert strip_version_suffix("Python 3.x") == "Python"
    assert strip_version_suffix("Java 17") == "Java"
    # No version suffix -> unchanged.
    assert strip_version_suffix("FastAPI") == "FastAPI"


def test_versioned_rule_skill_matches_base_in_resume() -> None:
    # JD lists versioned skills; resume names the base skill. They must match.
    detailed = match_skills_detailed(RESUME, ["Python 3.10", "PostgreSQL 15"])
    assert detailed["Python 3.10"].present is True
    assert detailed["PostgreSQL 15"].present is True


def test_expand_terms_includes_base_and_aliases() -> None:
    terms = [t.lower() for t in expand_skill_terms("PostgreSQL 14")]
    assert "postgresql 14" in terms  # the JD spelling
    assert "postgresql" in terms     # version-stripped base
    assert "postgres" in terms       # declared alias of the base


def test_related_but_different_skill_still_never_matches() -> None:
    # Guard the responsible-ai boundary: version stripping must not conflate distinct skills.
    assert match_skills_in_text("Experienced in Java and Spring.", ["JavaScript"]) == {
        "JavaScript": False
    }


# --- (c) Unverified / available evidence evaluates cleanly ------------------------------


def test_unverified_skill_routes_to_review_not_silent_zero_fail() -> None:
    # An UNCONFIRMED mandatory skill (not in the verified pool) must route to manual review,
    # never an automatic FAIL — missing evidence is not proof of absence (responsible-ai.md).
    evidence = EvidenceSet(verified_skills=set())
    node = {
        "criterion_type": "exact_skill", "name": "Docker", "skill_id": "docker",
        "operator": "contains_verified", "expected_value": "docker",
        "weight": 30, "mandatory": True, "missing_evidence": "manual_review",
    }
    outcome = evaluate_leaf(node, evidence)
    assert outcome.outcome is Outcome.MANUAL_REVIEW
    assert outcome.awarded_score == 0
    assert "review" in outcome.reason.lower()


def test_unverified_field_evidence_scores_when_above_confidence_floor() -> None:
    # A plain field criterion backed by UNVERIFIED but adequately-confident evidence is
    # evaluated cleanly and scores — being unverified does not force it to review.
    from app.rules_engine.evaluator import Evidence

    evidence = EvidenceSet(
        fields={"total_experience_years": Evidence(value="6", confidence=0.8, verified=False)}
    )
    node = {
        "criterion_type": "numeric_comparison", "name": "Experience",
        "field": "total_experience_years", "operator": "gte", "expected_value": 3,
        "weight": 40, "mandatory": True, "missing_evidence": "manual_review",
    }
    outcome = evaluate_leaf(node, evidence)
    assert outcome.outcome is Outcome.PASS
    assert outcome.awarded_score == 40


def test_missing_field_does_not_crash_and_routes_to_review() -> None:
    # No evidence at all for a mandatory field -> clean MANUAL_REVIEW with a reason, never
    # an exception and never a confirmed zero-fail.
    outcome = evaluate_leaf(
        {
            "criterion_type": "numeric_comparison", "name": "Experience",
            "field": "total_experience_years", "operator": "gte", "expected_value": 3,
            "weight": 40, "mandatory": True, "missing_evidence": "manual_review",
        },
        EvidenceSet(),
    )
    assert outcome.outcome is Outcome.MANUAL_REVIEW
    assert outcome.awarded_score == 0
    assert outcome.reason


# --- Tiered skill SCORING: good/nice-to-have contribute points --------------------------

from app.modules.rules.service import _skill_criterion  # noqa: E402
from app.rules_engine.dsl import SkillTier  # noqa: E402


def test_good_to_have_confirmed_skill_awards_its_weight() -> None:
    node = _skill_criterion("FastAPI", SkillTier.GOOD_TO_HAVE)
    evidence = EvidenceSet(verified_skills={"fastapi"})
    outcome = evaluate_leaf(node, evidence)
    assert outcome.outcome is Outcome.PASS
    assert outcome.awarded_score == node["weight"] > 0


def test_nice_to_have_confirmed_skill_awards_its_weight() -> None:
    node = _skill_criterion("Docker", SkillTier.NICE_TO_HAVE)
    evidence = EvidenceSet(verified_skills={"docker"})
    outcome = evaluate_leaf(node, evidence)
    assert outcome.outcome is Outcome.PASS
    assert outcome.awarded_score == node["weight"] > 0


def test_unconfirmed_optional_skill_scores_zero_without_review() -> None:
    # An absent GOOD_TO_HAVE must score 0 and NOT route to manual review (so a candidate
    # missing an optional skill still gets a clean score, not a stalled run). This is the
    # key difference from a mandatory skill, which routes to review.
    node = _skill_criterion("Kubernetes", SkillTier.GOOD_TO_HAVE)
    outcome = evaluate_leaf(node, EvidenceSet(verified_skills=set()))
    assert outcome.outcome is not Outcome.MANUAL_REVIEW
    assert outcome.awarded_score == 0
    assert outcome.mandatory is False


def test_skill_score_accumulates_across_tiers() -> None:
    # Two confirmed optional skills accumulate points; experience is not required to score.
    good = _skill_criterion("FastAPI", SkillTier.GOOD_TO_HAVE)
    nice = _skill_criterion("Docker", SkillTier.NICE_TO_HAVE)
    evidence = EvidenceSet(verified_skills={"fastapi", "docker"})
    total = sum(evaluate_leaf(n, evidence).awarded_score for n in (good, nice))
    assert total == good["weight"] + nice["weight"]
