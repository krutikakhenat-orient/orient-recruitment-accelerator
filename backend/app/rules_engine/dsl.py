"""Typed rules DSL: node types, operators, and validation (Req 7.1).

Rules are DATA, never code. A rule is a JSON object describing a single criterion or a
logical group of criteria. The validator accepts only a whitelisted set of node types and
operators and rejects anything malformed BEFORE a rule can be approved. The evaluator
(evaluator.py) interprets a validated tree; it never uses eval/exec and never runs
arbitrary code (steering/coding-standards.md, responsible-ai.md).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.core.errors import ValidationError


class CriterionType(str, Enum):
    BOOLEAN = "boolean"
    NUMERIC_COMPARISON = "numeric_comparison"
    NUMERIC_RANGE = "numeric_range"
    TEXT_ENUM = "text_enum"
    EXACT_SKILL = "exact_skill"
    SKILL_EXPERIENCE = "skill_experience"
    VERIFIED_CERTIFICATION = "verified_certification"
    EDUCATION = "education"
    LOCATION = "location"
    NOTICE_PERIOD = "notice_period"
    RELEVANT_EXPERIENCE = "relevant_experience"
    EVIDENCE_PRESENT = "evidence_present"
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    AND = "and"
    OR = "or"
    NOT = "not"


class Operator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    CONTAINS_VERIFIED = "contains_verified"


# Behaviours when evidence is missing or confidence is low.
class MissingBehaviour(str, Enum):
    FAIL = "fail"
    MANUAL_REVIEW = "manual_review"
    PASS = "pass"  # rarely appropriate; allowed but discouraged


class SkillTier(str, Enum):
    """Explicit skill-checklist tier for a leaf criterion (Req: categorised checklist).

    This is an optional, additive LABEL on a criterion. It does not change the
    deterministic maths — a criterion's gate behaviour is still driven by ``mandatory``
    and its score contribution by ``weight``. The tier makes the author's intent explicit
    and lets the UI group criteria and show per-tier match bars.

      - MUST_HAVE: a mandatory prerequisite. Convention: author also sets mandatory=True so
        a confirmed failure yields 0 points and (via missing_evidence=manual_review)
        unconfirmed evidence routes to the Review Queue. Never an automatic rejection.
      - GOOD_TO_HAVE: core weighted competency.
      - NICE_TO_HAVE: secondary/bonus weighted competency.
    """

    MUST_HAVE = "must_have"
    GOOD_TO_HAVE = "good_to_have"
    NICE_TO_HAVE = "nice_to_have"


LOGICAL_TYPES = {CriterionType.AND, CriterionType.OR, CriterionType.NOT}

# Operators valid for numeric comparisons.
_NUMERIC_OPERATORS = {Operator.EQ, Operator.NEQ, Operator.GT, Operator.GTE,
                      Operator.LT, Operator.LTE}

# criterion_type -> allowed operators
_ALLOWED_OPERATORS: dict[CriterionType, set[Operator]] = {
    CriterionType.NUMERIC_COMPARISON: _NUMERIC_OPERATORS,
    CriterionType.SKILL_EXPERIENCE: _NUMERIC_OPERATORS,
    CriterionType.RELEVANT_EXPERIENCE: _NUMERIC_OPERATORS,
    CriterionType.NOTICE_PERIOD: _NUMERIC_OPERATORS,
    CriterionType.CONFIDENCE_THRESHOLD: _NUMERIC_OPERATORS,
    CriterionType.TEXT_ENUM: {Operator.IN, Operator.EQ},
    CriterionType.LOCATION: {Operator.IN, Operator.EQ},
    CriterionType.EDUCATION: {Operator.IN, Operator.EQ},
    CriterionType.EXACT_SKILL: {Operator.CONTAINS_VERIFIED},
    CriterionType.VERIFIED_CERTIFICATION: {Operator.CONTAINS_VERIFIED},
    CriterionType.BOOLEAN: {Operator.EQ},
    CriterionType.EVIDENCE_PRESENT: {Operator.EQ},
    # numeric_range uses min/max, no single operator
    CriterionType.NUMERIC_RANGE: set(),
}


def validate_rule_node(node: object, *, path: str = "$") -> None:
    """Validate a single rule node (recursively for logical groups).

    Raises ValidationError on any unknown type/operator or structural problem. This runs
    at authoring/approval time so an invalid rule can never reach evaluation.
    """
    if not isinstance(node, dict):
        raise ValidationError(f"Rule node at {path} must be an object")

    raw_type = node.get("criterion_type")
    try:
        ctype = CriterionType(raw_type)
    except ValueError as exc:
        raise ValidationError(
            f"Unsupported criterion_type '{raw_type}' at {path}"
        ) from exc

    if ctype in LOGICAL_TYPES:
        _validate_logical(ctype, node, path)
        return

    _validate_leaf(ctype, node, path)


def _validate_logical(ctype: CriterionType, node: dict[str, Any], path: str) -> None:
    if ctype is CriterionType.NOT:
        child = node.get("child")
        if child is None:
            raise ValidationError(f"'not' node at {path} requires a 'child'")
        validate_rule_node(child, path=f"{path}.child")
        return
    children = node.get("children")
    if not isinstance(children, list) or not children:
        raise ValidationError(
            f"'{ctype.value}' node at {path} requires a non-empty 'children' list"
        )
    for i, child in enumerate(children):
        validate_rule_node(child, path=f"{path}.children[{i}]")


def _validate_leaf(ctype: CriterionType, node: dict[str, Any], path: str) -> None:
    # Weight must be a non-negative number.
    weight = node.get("weight", 0)
    if not isinstance(weight, int | float) or isinstance(weight, bool) or weight < 0:
        raise ValidationError(f"'weight' at {path} must be a non-negative number")

    # mandatory must be a bool if present.
    if "mandatory" in node and not isinstance(node["mandatory"], bool):
        raise ValidationError(f"'mandatory' at {path} must be a boolean")

    # tier, if present, must be one of the whitelisted skill tiers.
    if "tier" in node:
        try:
            SkillTier(node["tier"])
        except ValueError as exc:
            raise ValidationError(
                f"'tier' at {path} must be one of {[t.value for t in SkillTier]}"
            ) from exc

    # Validate missing/low-confidence behaviours if present.
    for key in ("missing_evidence", "low_confidence"):
        if key in node:
            try:
                MissingBehaviour(node[key])
            except ValueError as exc:
                raise ValidationError(
                    f"'{key}' at {path} must be one of "
                    f"{[b.value for b in MissingBehaviour]}"
                ) from exc

    if ctype is CriterionType.NUMERIC_RANGE:
        _validate_range(node, path)
        return

    # Operator must be present and allowed for this criterion type.
    raw_op = node.get("operator")
    try:
        op = Operator(raw_op)
    except ValueError as exc:
        raise ValidationError(f"Unsupported operator '{raw_op}' at {path}") from exc
    allowed = _ALLOWED_OPERATORS.get(ctype, set())
    if op not in allowed:
        raise ValidationError(
            f"Operator '{op.value}' is not valid for criterion_type "
            f"'{ctype.value}' at {path}"
        )

    if "expected_value" not in node:
        raise ValidationError(f"'expected_value' is required at {path}")

    # Skill / certification criteria require a skill/field identifier.
    if ctype in {CriterionType.EXACT_SKILL, CriterionType.SKILL_EXPERIENCE} and not node.get(
        "skill_id"
    ):
        raise ValidationError(f"'skill_id' is required for {ctype.value} at {path}")


def _validate_range(node: dict[str, Any], path: str) -> None:
    lo = node.get("min")
    hi = node.get("max")
    if not isinstance(lo, int | float) or isinstance(lo, bool):
        raise ValidationError(f"numeric_range at {path} requires numeric 'min'")
    if not isinstance(hi, int | float) or isinstance(hi, bool):
        raise ValidationError(f"numeric_range at {path} requires numeric 'max'")
    if hi < lo:
        raise ValidationError(f"numeric_range at {path} has max < min")


def validate_rule_set(rules: list[dict[str, Any]]) -> None:
    """Validate every rule in a set. Raises on the first invalid rule."""
    if not isinstance(rules, list) or not rules:
        raise ValidationError("A rule set must contain at least one rule")
    for i, rule in enumerate(rules):
        validate_rule_node(rule, path=f"rules[{i}]")
