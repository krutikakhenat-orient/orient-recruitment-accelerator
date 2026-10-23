"""Tests for the ORA feature refactor: 3-tier roles, skill tiers, self-assessment
conflict detection, and audited candidate-PII reveal.

All guarantees under test: deterministic rules, zero AI auto-rejection, evidence-backed
routing to human review, and audited PII access. Synthetic data only.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.audit.service import verify_chain
from app.modules.candidates import service as candidate_service
from app.modules.extraction.models import ExtractedField, VerificationStatus
from app.modules.identity.permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    OPERATIONAL_ROLES,
    Permission,
    RoleName,
)
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.rules import service as rules_service
from app.modules.screening import service as screening_service
from app.rules_engine.dsl import SkillTier, validate_rule_set
from app.rules_engine.evaluator import EvidenceSet, evaluate_node
from tests.factories import make_org

CAMPAIGN = uuid.uuid4()


# --------------------------------------------------------------------------- roles


def test_operational_roles_are_canonical() -> None:
    # 3-tier operational model: Recruiter (author), Recruiter Admin (approve + hiring
    # manager duties), Interview Panel (assess). Hiring Manager was folded into Recruiter
    # Admin; it is no longer a separate role.
    assert OPERATIONAL_ROLES == (
        RoleName.RECRUITER,
        RoleName.RECRUITER_ADMIN,
        RoleName.INTERVIEW_PANEL,
    )
    # Removed legacy roles no longer exist.
    assert not hasattr(RoleName, "HR_HEAD")
    assert not hasattr(RoleName, "RECRUITMENT_ADMIN")
    assert not hasattr(RoleName, "HIRING_MANAGER")


def test_recruiter_admin_has_full_operational_authority() -> None:
    perms = DEFAULT_ROLE_PERMISSIONS[RoleName.RECRUITER_ADMIN]
    for required in (
        Permission.JD_APPROVE, Permission.RULE_APPROVE, Permission.SCREENING_EXECUTE,
        Permission.INTERVIEW_SCHEDULE, Permission.INTERVIEW_APPROVE,
        Permission.HIRING_DECISION_APPROVE, Permission.CANDIDATE_VIEW_PII,
    ):
        assert required in perms


def test_recruiter_authors_but_cannot_approve() -> None:
    """Separation of duties: a Recruiter can create rules/JDs but holds no approval
    authority, so a different Recruiter Admin must approve its work (four-eyes)."""
    perms = DEFAULT_ROLE_PERMISSIONS[RoleName.RECRUITER]
    assert Permission.RULE_CREATE in perms
    assert Permission.JD_UPLOAD in perms
    assert Permission.SCREENING_EXECUTE in perms
    # No approval authorities.
    assert Permission.RULE_APPROVE not in perms
    assert Permission.JD_APPROVE not in perms
    assert Permission.CAMPAIGN_APPROVE not in perms
    assert Permission.HIRING_DECISION_APPROVE not in perms


def test_interview_panel_is_restricted_to_assessment() -> None:
    assert DEFAULT_ROLE_PERMISSIONS[RoleName.INTERVIEW_PANEL] == {Permission.ASSESSMENT_SUBMIT}


def test_recruiter_admin_carries_hiring_manager_duties_not_system_admin() -> None:
    # Hiring Manager was consolidated into Recruiter Admin: it holds the hiring-manager
    # duties (JD approve, candidate review, interview approve, hiring recommend AND approve)
    # but NOT system administration (user lifecycle / system config), which stays on
    # SYSTEM_ADMIN.
    perms = DEFAULT_ROLE_PERMISSIONS[RoleName.RECRUITER_ADMIN]
    assert Permission.JD_APPROVE in perms
    assert Permission.APPLICATION_REVIEW in perms
    assert Permission.INTERVIEW_APPROVE in perms
    assert Permission.HIRING_DECISION_RECOMMEND in perms
    assert Permission.HIRING_DECISION_APPROVE in perms
    # System administration is NOT bundled into the recruitment-governance role.
    assert Permission.USER_MANAGE not in perms
    assert Permission.SYSTEM_CONFIGURE not in perms


# ------------------------------------------------------------------- skill tiers


def test_valid_tier_is_accepted_and_bad_tier_rejected() -> None:
    good = [{
        "rule_id": "R", "name": "Py", "criterion_type": "exact_skill", "skill_id": "python",
        "operator": "contains_verified", "expected_value": "python", "weight": 10,
        "tier": SkillTier.GOOD_TO_HAVE.value,
    }]
    validate_rule_set(good)  # no raise

    bad = [dict(good[0], tier="super_nice")]
    with pytest.raises(ValidationError, match="tier"):
        validate_rule_set(bad)


def test_tier_is_passthrough_and_does_not_change_outcome() -> None:
    node = {
        "rule_id": "R", "name": "Py", "criterion_type": "exact_skill", "skill_id": "python",
        "operator": "contains_verified", "expected_value": "python", "weight": 10,
        "tier": SkillTier.MUST_HAVE.value,
    }
    evidence = EvidenceSet(verified_skills={"python"})
    _, leaves = evaluate_node(node, evidence)
    assert leaves[0].tier == "must_have"
    assert leaves[0].outcome.value == "pass"
    assert leaves[0].awarded_score == 10

    # Same criterion WITHOUT a tier yields an identical outcome/score (determinism).
    node_no_tier = {k: v for k, v in node.items() if k != "tier"}
    _, leaves2 = evaluate_node(node_no_tier, evidence)
    assert leaves2[0].outcome == leaves[0].outcome
    assert leaves2[0].awarded_score == leaves[0].awarded_score
    assert leaves2[0].tier is None


# ----------------------------------------------- self-assessment conflict detection


def _make_application(db_session, org, answers):  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id, campaign_id=CAMPAIGN, candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(), answers=answers,
        state=ApplicationState.EXTRACTION_REVIEW.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def _field(org, app, name, value, *, confidence=1.0, status=VerificationStatus.VERIFIED):  # type: ignore[no-untyped-def]
    verified = value if status is VerificationStatus.VERIFIED else None
    return ExtractedField(
        organisation_id=org.id, application_id=app.id, field_name=name,
        extracted_value=value, verified_value=verified,
        status=status.value, extraction_method="manual", confidence=confidence,
    )


def test_claim_exceeding_evidence_is_flagged() -> None:
    # Candidate claims 10 years; resume evidence confirms only 3.
    findings = screening_service.detect_self_assessment_conflicts(
        {"total_experience_years": "10"},
        [_SimpleField("total_experience_years", "3", 1.0, VerificationStatus.VERIFIED)],
    )
    assert len(findings) == 1
    assert "exceeds verified resume evidence" in findings[0].reason


def test_low_confidence_backing_is_flagged() -> None:
    # A non-numeric self-claim that DIFFERS from low-confidence resume evidence is flagged
    # for human review (the claim cannot be considered verified).
    findings = screening_service.detect_self_assessment_conflicts(
        {"current_location": "Bangalore"},
        [_SimpleField("current_location", "Mumbai", 0.4, VerificationStatus.UNVERIFIED)],
    )
    assert len(findings) == 1
    assert "low-confidence" in findings[0].reason


def test_corroborating_low_confidence_value_is_not_a_conflict() -> None:
    # Regression guard: a self-claim that AGREES with the resume evidence must NOT be flagged
    # as a conflict merely because the extraction confidence is low. Previously this fired a
    # spurious "data conflict" on every candidate (e.g. their own name matched a 0.60-
    # confidence extracted name), which blocked auto-progression to the interview panel.
    numeric = screening_service.detect_self_assessment_conflicts(
        {"total_experience_years": "3"},
        [_SimpleField("total_experience_years", "3", 0.4, VerificationStatus.UNVERIFIED)],
    )
    assert numeric == []
    text = screening_service.detect_self_assessment_conflicts(
        {"full_name": "Rohan Deshmukh"},
        [_SimpleField("full_name", "Rohan Deshmukh", 0.6, VerificationStatus.UNVERIFIED)],
    )
    assert text == []


def test_placeholder_answer_is_not_a_conflict() -> None:
    # A walk-in placeholder ("to be confirmed") is not a verifiable self-claim.
    findings = screening_service.detect_self_assessment_conflicts(
        {"skills": "Walk-in — to be confirmed"},
        [_SimpleField("skills", "Python", 0.4, VerificationStatus.UNVERIFIED)],
    )
    assert findings == []


def test_system_recovered_experience_is_not_a_conflict() -> None:
    # Walk-in: experience was recovered from the resume text by the fallback (not a candidate
    # self-claim). Low confidence alone must NOT raise a "data conflict" for it.
    findings = screening_service.detect_self_assessment_conflicts(
        {"total_experience_years": "7"},
        [
            _SimpleField(
                "total_experience_years", "7", 0.4, VerificationStatus.UNVERIFIED,
                extraction_method="resume_text_fallback",
            )
        ],
    )
    assert findings == []


def test_recovered_value_still_flags_when_claim_exceeds_it() -> None:
    # A genuine claim that EXCEEDS even the recovered evidence is still a real conflict.
    findings = screening_service.detect_self_assessment_conflicts(
        {"total_experience_years": "12"},
        [
            _SimpleField(
                "total_experience_years", "7", 0.4, VerificationStatus.UNVERIFIED,
                extraction_method="resume_text_fallback",
            )
        ],
    )
    assert len(findings) == 1
    assert "exceeds" in findings[0].reason


def test_no_resume_evidence_is_not_a_conflict() -> None:
    # Absence of evidence is NOT proof of absence (responsible-ai.md).
    findings = screening_service.detect_self_assessment_conflicts(
        {"total_experience_years": "10"}, []
    )
    assert findings == []


def test_matching_claim_is_not_a_conflict() -> None:
    findings = screening_service.detect_self_assessment_conflicts(
        {"total_experience_years": "3"},
        [_SimpleField("total_experience_years", "3", 1.0, VerificationStatus.VERIFIED)],
    )
    assert findings == []


def test_conflict_routes_to_review_without_auto_rejecting(db_session) -> None:
    org = make_org(db_session)
    app = _make_application(db_session, org, {"total_experience_years": "10"})
    db_session.add(_field(org, app, "total_experience_years", "3", confidence=1.0))
    db_session.flush()

    rules = [{
        "rule_id": "R-EXP", "name": "Experience", "criterion_type": "numeric_comparison",
        "field": "total_experience_years", "operator": "gte", "expected_value": 3,
        "weight": 100, "mandatory": True, "missing_evidence": "manual_review",
        "tier": "must_have",
    }]
    version = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="rs",
        rules=rules, actor_id=uuid.uuid4(),
    )
    approved = rules_service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=version.id, approver_id=uuid.uuid4(),
    )
    actor = AuthenticatedActor(
        user_id=uuid.uuid4(), organisation_id=org.id, email="screener@example.com",
        role_names=["recruiter_admin"],
        permissions={Permission.SCREENING_EXECUTE.value, Permission.APPLICATION_REVIEW.value},
        assigned_campaign_ids={CAMPAIGN},
    )
    result = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=approved, threshold_version=None, actor=actor,
    )
    run = result.run
    assert run.conflict_flagged is True
    assert run.manual_review_required is True
    assert run.recommendation == "data_conflict"
    # Never rejected — routed to a human instead.
    assert app.state == ApplicationState.MANUAL_REVIEW.value


# -------------------------------------------------- audited candidate PII reveal


def test_reveal_contact_audits_the_access(db_session) -> None:
    org = make_org(db_session)
    resolution = candidate_service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="SYNTHETIC Pat",
        email="synthetic.pat@example.com", mobile="+14155550111",
    )
    actor_id = uuid.uuid4()
    revealed = candidate_service.reveal_contact(
        db_session, organisation_id=org.id, candidate_id=resolution.candidate.id,
        actor_id=actor_id,
    )
    assert revealed.email == "synthetic.pat@example.com"
    # The access is recorded in the tamper-evident audit chain.
    from app.modules.audit.models import AuditEvent

    events = db_session.query(AuditEvent).filter(
        AuditEvent.action == "candidate.contact_revealed"
    ).all()
    assert len(events) == 1
    assert events[0].entity_id == str(resolution.candidate.id)
    assert verify_chain(db_session, org.id) is True


# --- a tiny in-memory stand-in for ExtractedField for the pure-function conflict tests


class _SimpleField:
    def __init__(self, field_name, value, confidence, status, extraction_method="manual"):  # type: ignore[no-untyped-def]
        self.field_name = field_name
        self._value = value
        self.confidence = confidence
        self.status = status.value
        self.extraction_method = extraction_method

    @property
    def effective_value(self):  # type: ignore[no-untyped-def]
        return self._value
