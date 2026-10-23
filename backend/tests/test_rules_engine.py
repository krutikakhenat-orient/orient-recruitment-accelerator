"""Tests for the typed-JSON rules DSL validation and deterministic evaluator (Req 7.1)."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.rules_engine.dsl import validate_rule_node, validate_rule_set
from app.rules_engine.evaluator import (
    Evidence,
    EvidenceSet,
    Outcome,
    evaluate_node,
)


def _skill_rule(years: int = 3, mandatory: bool = True) -> dict:
    return {
        "rule_id": "RULE-VMWARE-001", "name": "Minimum VMware experience",
        "criterion_type": "skill_experience", "skill_id": "SKILL-VMWARE",
        "operator": "gte", "expected_value": years, "unit": "years",
        "mandatory": mandatory, "weight": 20,
        "missing_evidence": "manual_review", "low_confidence": "manual_review",
    }


# --- DSL validation ------------------------------------------------------------

def test_valid_rule_passes_validation() -> None:
    validate_rule_node(_skill_rule())


def test_unknown_criterion_type_rejected() -> None:
    with pytest.raises(ValidationError, match="Unsupported criterion_type"):
        validate_rule_node({"criterion_type": "telepathy", "operator": "gte",
                            "expected_value": 1})


def test_unsupported_operator_rejected() -> None:
    with pytest.raises(ValidationError, match="Unsupported operator"):
        validate_rule_node({"criterion_type": "numeric_comparison", "field": "x",
                            "operator": "approximately", "expected_value": 1})


def test_operator_not_valid_for_type_rejected() -> None:
    # 'in' is not valid for a numeric comparison.
    with pytest.raises(ValidationError, match="not valid for criterion_type"):
        validate_rule_node({"criterion_type": "numeric_comparison", "field": "x",
                            "operator": "in", "expected_value": [1, 2]})


def test_numeric_range_requires_min_max() -> None:
    with pytest.raises(ValidationError, match="requires numeric 'min'"):
        validate_rule_node({"criterion_type": "numeric_range", "field": "x", "max": 5})


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        validate_rule_node({"criterion_type": "numeric_comparison", "field": "x",
                            "operator": "gte", "expected_value": 1, "weight": -5})


def test_empty_rule_set_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one rule"):
        validate_rule_set([])


def test_logical_group_validates_children() -> None:
    group = {"criterion_type": "and", "children": [_skill_rule(), _skill_rule(years=5)]}
    validate_rule_node(group)
    bad = {"criterion_type": "and", "children": []}
    with pytest.raises(ValidationError, match="non-empty 'children'"):
        validate_rule_node(bad)


# --- Deterministic evaluation --------------------------------------------------

def _evidence_with_experience(years: float) -> EvidenceSet:
    ev = EvidenceSet()
    ev.skill_experience_years["SKILL-VMWARE"] = years
    return ev


def test_experience_pass_and_fail() -> None:
    rule = _skill_rule(years=3)
    passed, leaves = evaluate_node(rule, _evidence_with_experience(5))
    assert passed is Outcome.PASS
    assert leaves[0].awarded_score == 20

    failed, _ = evaluate_node(rule, _evidence_with_experience(1))
    assert failed is Outcome.FAIL


def test_missing_evidence_routes_to_review_not_fail() -> None:
    # No experience evidence at all; missing_evidence='manual_review'.
    outcome, leaves = evaluate_node(_skill_rule(), EvidenceSet())
    assert outcome is Outcome.MANUAL_REVIEW
    assert leaves[0].awarded_score == 0


def test_low_confidence_routes_to_review() -> None:
    rule = {
        "criterion_type": "numeric_comparison", "name": "experience", "field": "exp",
        "operator": "gte", "expected_value": 3, "weight": 10,
        "low_confidence": "manual_review", "confidence_floor": 0.6,
    }
    ev = EvidenceSet(fields={"exp": Evidence(value=5, confidence=0.3)})
    outcome, _ = evaluate_node(rule, ev)
    assert outcome is Outcome.MANUAL_REVIEW


def test_determinism_identical_inputs_identical_results() -> None:
    rule = _skill_rule(years=3)
    ev = _evidence_with_experience(4)
    first, first_leaves = evaluate_node(rule, ev)
    second, second_leaves = evaluate_node(rule, _evidence_with_experience(4))
    assert first == second
    assert first_leaves[0].awarded_score == second_leaves[0].awarded_score
    assert first_leaves[0].reason == second_leaves[0].reason


def test_and_group_blocks_on_single_fail() -> None:
    group = {
        "criterion_type": "and",
        "children": [_skill_rule(years=3), _skill_rule(years=10)],
    }
    outcome, _ = evaluate_node(group, _evidence_with_experience(5))
    assert outcome is Outcome.FAIL  # second child (>=10) fails


def test_exact_skill_requires_verified_evidence() -> None:
    rule = {"criterion_type": "exact_skill", "name": "Linux", "skill_id": "linux",
            "operator": "contains_verified", "expected_value": "linux", "weight": 5,
            "missing_evidence": "manual_review"}
    ev = EvidenceSet(verified_skills={"linux"})
    passed, _ = evaluate_node(rule, ev)
    assert passed is Outcome.PASS
    # Without verified evidence -> review (not fail).
    missing, _ = evaluate_node(rule, EvidenceSet())
    assert missing is Outcome.MANUAL_REVIEW


# --- JD -> tiered scoring rule-set builder --------------------------------------------

from app.modules.rules.service import (  # noqa: E402
    build_rules_from_jd,
    build_skill_rules_from_jd,
)


def test_build_skill_rules_assigns_tiers_and_scoring_behaviour() -> None:
    rules = build_skill_rules_from_jd(
        mandatory_skills=["Python"],
        desirable_skills=["FastAPI"],
        nice_to_have_skills=["Docker"],
    )
    by_name = {r["name"]: r for r in rules}

    # Must-have is a mandatory gate that routes an unconfirmed skill to review.
    assert by_name["Python"]["mandatory"] is True
    assert by_name["Python"]["tier"] == "must_have"
    assert by_name["Python"]["missing_evidence"] == "manual_review"

    # Good-to-have and nice-to-have are weighted, NOT mandatory. An unconfirmed optional
    # skill scores 0 (missing_evidence=fail) but STAYS in the weighted denominator, so it
    # correctly lowers the fit percentage (honest weighted scoring) without forcing the whole
    # run to review. A confirmed optional skill earns its full weight.
    assert by_name["FastAPI"]["mandatory"] is False
    assert by_name["FastAPI"]["tier"] == "good_to_have"
    assert by_name["FastAPI"]["missing_evidence"] == "fail"
    assert by_name["Docker"]["tier"] == "nice_to_have"
    assert by_name["Docker"]["missing_evidence"] == "fail"
    assert by_name["Docker"]["weight"] > 0

    # The whole set is valid typed-JSON DSL.
    validate_rule_set(rules)


def test_build_skill_rules_dedupes_keeping_highest_tier() -> None:
    rules = build_skill_rules_from_jd(
        mandatory_skills=["Python"], desirable_skills=["python"]
    )
    python_rules = [r for r in rules if r["skill_id"] == "python"]
    assert len(python_rules) == 1
    assert python_rules[0]["tier"] == "must_have"


def test_build_rules_from_jd_combines_skills_and_experience() -> None:
    rules = build_rules_from_jd(
        mandatory_skills=["Python"],
        desirable_skills=["FastAPI"],
        minimum_total_experience_years=3,
    )
    types = {r["criterion_type"] for r in rules}
    assert "exact_skill" in types
    assert "numeric_comparison" in types  # the experience criterion is included
    exp = next(r for r in rules if r["criterion_type"] == "numeric_comparison")
    assert exp["field"] == "total_experience_years"
    assert exp["weight"] > 0
    validate_rule_set(rules)


def test_build_rules_from_jd_omits_experience_when_absent() -> None:
    rules = build_rules_from_jd(
        mandatory_skills=["Python"], desirable_skills=[], minimum_total_experience_years=None
    )
    assert all(r["criterion_type"] == "exact_skill" for r in rules)


def test_build_skills_drops_experience_sentences_mis_entered_as_skills() -> None:
    # Regression: an experience sentence captured into the JD skills list must NOT become a
    # skill criterion (it would never match a resume and force a 0 skill score).
    rules = build_skill_rules_from_jd(
        mandatory_skills=["Minimum Total Experience: 1 year", "Python"],
        desirable_skills=["5+ years experience", "FastAPI"],
    )
    names = {r["name"] for r in rules}
    assert "Python" in names
    assert "FastAPI" in names
    assert "Minimum Total Experience: 1 year" not in names
    assert "5+ years experience" not in names
    # Only the genuine skills produced criteria.
    assert len(rules) == 2


def test_build_rules_from_jd_scores_skills_plus_experience_separately() -> None:
    # The experience target is a numeric criterion; the skills are exact_skill criteria.
    rules = build_rules_from_jd(
        mandatory_skills=["Minimum Total Experience: 1 year", "Python"],
        desirable_skills=["FastAPI"],
        minimum_total_experience_years=1,
    )
    skill_names = {r["name"] for r in rules if r["criterion_type"] == "exact_skill"}
    assert skill_names == {"Python", "FastAPI"}
    assert any(r["criterion_type"] == "numeric_comparison" for r in rules)
