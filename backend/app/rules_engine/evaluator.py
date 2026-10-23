"""Deterministic rules evaluator (Req 7.1, 8.1, 8.3).

Interprets a validated rule tree against a candidate evidence set. The evaluator is PURE
and DETERMINISTIC: the same (evidence, rules, engine version) always yields identical
results, so a screening run is reproducible. No eval/exec; only whitelisted node types
and operators (validated upstream by dsl.py).

Each leaf criterion resolves to an outcome:
- PASS: the criterion is satisfied by verified/available evidence.
- FAIL: the criterion is contradicted by available evidence.
- MANUAL_REVIEW: evidence is missing, low-confidence, or conflicting and the rule's
  configured behaviour routes it to a human. Missing evidence is NEVER an automatic FAIL
  unless the rule explicitly sets missing_evidence='fail'.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.rules_engine.dsl import CriterionType, MissingBehaviour, Operator

ENGINE_VERSION = "1.0.0"


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    MANUAL_REVIEW = "manual_review"


@dataclass
class Evidence:
    """A single piece of candidate evidence available to the evaluator."""

    value: Any
    confidence: float = 1.0
    verified: bool = False
    source_ref: str | None = None


@dataclass
class EvidenceSet:
    """Normalised evidence keyed by field name, plus verified skills/certifications."""

    fields: dict[str, Evidence] = field(default_factory=dict)
    verified_skills: set[str] = field(default_factory=set)       # canonical skill ids
    verified_certifications: set[str] = field(default_factory=set)
    # Per-skill experience in years (from verified evidence) keyed by skill id.
    skill_experience_years: dict[str, float] = field(default_factory=dict)

    def get(self, name: str) -> Evidence | None:
        return self.fields.get(name)


@dataclass
class CriterionOutcome:
    criterion_name: str
    criterion_type: str
    mandatory: bool
    outcome: Outcome
    expected: Any
    candidate_evidence: Any
    evidence_source: str | None
    confidence: float | None
    max_score: float
    awarded_score: float
    reason: str
    # Optional skill-checklist tier label (must_have / good_to_have / nice_to_have).
    # Passthrough only — it never influences the deterministic outcome or score.
    tier: str | None = None


# Minimum confidence to accept evidence without routing to review.
DEFAULT_CONFIDENCE_FLOOR = 0.5


def _missing_behaviour(node: dict[str, Any], key: str) -> MissingBehaviour:
    return MissingBehaviour(node.get(key, MissingBehaviour.MANUAL_REVIEW.value))


def _compare_numeric(op: Operator, actual: float, expected: float) -> bool:
    return {
        Operator.EQ: actual == expected,
        Operator.NEQ: actual != expected,
        Operator.GT: actual > expected,
        Operator.GTE: actual >= expected,
        Operator.LT: actual < expected,
        Operator.LTE: actual <= expected,
    }[op]


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_leaf(node: dict[str, Any], evidence: EvidenceSet) -> CriterionOutcome:
    ctype = CriterionType(node["criterion_type"])
    name = node.get("name", node.get("rule_id", ctype.value))
    mandatory = bool(node.get("mandatory", False))
    weight = float(node.get("weight", 0))
    tier = node.get("tier")
    confidence_floor = float(node.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR))

    def result(outcome: Outcome, cand: Any, source: str | None, conf: float | None,
               reason: str, awarded: float) -> CriterionOutcome:
        return CriterionOutcome(
            criterion_name=str(name), criterion_type=ctype.value, mandatory=mandatory,
            outcome=outcome, expected=node.get("expected_value", node.get("max")),
            candidate_evidence=cand, evidence_source=source, confidence=conf,
            max_score=weight, awarded_score=awarded, reason=reason,
            tier=str(tier) if tier is not None else None,
        )

    # --- Skill / certification criteria operate on verified sets. ---
    if ctype in {CriterionType.EXACT_SKILL, CriterionType.VERIFIED_CERTIFICATION}:
        target = str(node.get("expected_value") or node.get("skill_id") or "").lower()
        pool = (evidence.verified_skills if ctype is CriterionType.EXACT_SKILL
                else evidence.verified_certifications)
        present = target in {p.lower() for p in pool}
        if present:
            return result(Outcome.PASS, target, "verified", 1.0,
                          "Verified evidence present", weight)
        behaviour = _missing_behaviour(node, "missing_evidence")
        return _apply_missing(result, behaviour, weight,
                              f"No verified evidence for '{target}'")

    if ctype is CriterionType.SKILL_EXPERIENCE:
        skill_id = str(node.get("skill_id") or "")
        years = evidence.skill_experience_years.get(skill_id)
        expected = _as_float(node.get("expected_value"))
        if years is None:
            behaviour = _missing_behaviour(node, "missing_evidence")
            return _apply_missing(result, behaviour, weight,
                                  f"No experience evidence for skill '{skill_id}'")
        op = Operator(node["operator"])
        passed = _compare_numeric(op, years, expected or 0)
        return result(Outcome.PASS if passed else Outcome.FAIL, years, "verified", 1.0,
                      f"{years} years vs required {op.value} {expected}",
                      weight if passed else 0.0)

    if ctype is CriterionType.EVIDENCE_PRESENT:
        field_name = str(node.get("field") or node.get("expected_value") or "")
        ev = evidence.get(field_name)
        if ev is not None and ev.value not in (None, "", []):
            return result(Outcome.PASS, ev.value, ev.source_ref, ev.confidence,
                          f"Evidence present for '{field_name}'", weight)
        behaviour = _missing_behaviour(node, "missing_evidence")
        return _apply_missing(result, behaviour, weight,
                              f"Evidence absent for '{field_name}'")

    if ctype is CriterionType.CONFIDENCE_THRESHOLD:
        field_name = str(node.get("field") or "")
        ev = evidence.get(field_name)
        expected = _as_float(node.get("expected_value")) or 0.0
        if ev is None:
            return _apply_missing(result, _missing_behaviour(node, "missing_evidence"),
                                  weight, f"No evidence for '{field_name}'")
        op = Operator(node["operator"])
        passed = _compare_numeric(op, ev.confidence, expected)
        return result(Outcome.PASS if passed else Outcome.MANUAL_REVIEW, ev.confidence,
                      ev.source_ref, ev.confidence,
                      f"Confidence {ev.confidence} vs {op.value} {expected}",
                      weight if passed else 0.0)

    # --- Field-based criteria (numeric / text / boolean / range). ---
    field_name = str(node.get("field") or node.get("criterion_type"))
    ev = evidence.get(field_name)
    if ev is None:
        return _apply_missing(result, _missing_behaviour(node, "missing_evidence"),
                              weight, f"No evidence for '{field_name}'")

    # Low confidence routes to review unless configured otherwise.
    if ev.confidence < confidence_floor:
        return _apply_missing(result, _missing_behaviour(node, "low_confidence"),
                              weight,
                              f"Low confidence ({ev.confidence}) for '{field_name}'",
                              cand=ev.value, source=ev.source_ref, conf=ev.confidence)

    passed = _evaluate_field(ctype, node, ev.value)
    return result(Outcome.PASS if passed else Outcome.FAIL, ev.value, ev.source_ref,
                  ev.confidence,
                  f"{field_name}={ev.value!r} vs {node.get('operator', 'range')} "
                  f"{node.get('expected_value', (node.get('min'), node.get('max')))}",
                  weight if passed else 0.0)


def _evaluate_field(ctype: CriterionType, node: dict[str, Any], value: Any) -> bool:
    if ctype is CriterionType.NUMERIC_RANGE:
        num = _as_float(value)
        if num is None:
            return False
        return float(node["min"]) <= num <= float(node["max"])

    op = Operator(node["operator"])
    expected = node.get("expected_value")

    if ctype is CriterionType.BOOLEAN:
        return bool(value) == bool(expected)

    if ctype in {CriterionType.TEXT_ENUM, CriterionType.LOCATION, CriterionType.EDUCATION}:
        text = str(value).strip().lower()
        if op is Operator.IN:
            allowed = [str(x).strip().lower() for x in (expected or [])]
            return text in allowed
        return text == str(expected).strip().lower()

    # Numeric comparison / notice period / relevant experience.
    num = _as_float(value)
    exp = _as_float(expected)
    if num is None or exp is None:
        return False
    return _compare_numeric(op, num, exp)


_ResultFn = Callable[[Outcome, Any, str | None, float | None, str, float], CriterionOutcome]


def _apply_missing(result_fn: _ResultFn, behaviour: MissingBehaviour, weight: float,
                   reason: str, *, cand: Any = None, source: str | None = None,
                   conf: float | None = None) -> CriterionOutcome:
    if behaviour is MissingBehaviour.FAIL:
        return result_fn(Outcome.FAIL, cand, source, conf, reason + " (treated as fail)", 0.0)
    if behaviour is MissingBehaviour.PASS:
        return result_fn(Outcome.PASS, cand, source, conf, reason + " (treated as pass)",
                         weight)
    return result_fn(Outcome.MANUAL_REVIEW, cand, source, conf,
                     reason + " (routed to manual review)", 0.0)


def evaluate_node(
    node: dict[str, Any], evidence: EvidenceSet
) -> tuple[Outcome, list[CriterionOutcome]]:
    """Evaluate a node (leaf or logical group). Returns the overall outcome plus the flat
    list of leaf outcomes encountered (for the explainable score)."""
    ctype = CriterionType(node["criterion_type"])

    if ctype is CriterionType.AND:
        outcomes: list[CriterionOutcome] = []
        agg = Outcome.PASS
        for child in node["children"]:
            child_outcome, child_leaves = evaluate_node(child, evidence)
            outcomes.extend(child_leaves)
            agg = _combine_and(agg, child_outcome)
        return agg, outcomes

    if ctype is CriterionType.OR:
        outcomes = []
        agg = Outcome.FAIL
        for child in node["children"]:
            child_outcome, child_leaves = evaluate_node(child, evidence)
            outcomes.extend(child_leaves)
            agg = _combine_or(agg, child_outcome)
        return agg, outcomes

    if ctype is CriterionType.NOT:
        child_outcome, child_leaves = evaluate_node(node["child"], evidence)
        return _negate(child_outcome), child_leaves

    leaf = evaluate_leaf(node, evidence)
    return leaf.outcome, [leaf]


def _combine_and(a: Outcome, b: Outcome) -> Outcome:
    if Outcome.FAIL in (a, b):
        return Outcome.FAIL
    if Outcome.MANUAL_REVIEW in (a, b):
        return Outcome.MANUAL_REVIEW
    return Outcome.PASS


def _combine_or(a: Outcome, b: Outcome) -> Outcome:
    if Outcome.PASS in (a, b):
        return Outcome.PASS
    if Outcome.MANUAL_REVIEW in (a, b):
        return Outcome.MANUAL_REVIEW
    return Outcome.FAIL


def _negate(a: Outcome) -> Outcome:
    if a is Outcome.PASS:
        return Outcome.FAIL
    if a is Outcome.FAIL:
        return Outcome.PASS
    return Outcome.MANUAL_REVIEW
