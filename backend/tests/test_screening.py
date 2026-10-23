"""Tests for the screening service and human review (Req 8.1-8.3, 9.1, 11.2;
AC-08, AC-09, AC-10, AC-13)."""

from __future__ import annotations

import uuid

from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.extraction.models import ExtractedField, VerificationStatus
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.review import service as review_service
from app.modules.review.models import ReviewAction, ReviewActionType, ReviewItem
from app.modules.rules import service as rules_service
from app.modules.screening import service as screening_service
from app.modules.screening.models import ScreeningRun
from tests.factories import make_org

CAMPAIGN = uuid.uuid4()

RULES = [
    {"rule_id": "R-EXP", "name": "Total experience", "criterion_type": "numeric_comparison",
     "field": "total_experience_years", "operator": "gte", "expected_value": 3,
     "weight": 40, "mandatory": True, "missing_evidence": "manual_review"},
    {"rule_id": "R-LOC", "name": "Location", "criterion_type": "location",
     "field": "current_location", "operator": "in",
     "expected_value": ["remote", "bangalore"], "weight": 20, "mandatory": False},
    {"rule_id": "R-SKILL", "name": "Linux verified", "criterion_type": "exact_skill",
     "skill_id": "linux", "operator": "contains_verified", "expected_value": "linux",
     "weight": 40, "mandatory": False, "missing_evidence": "manual_review"},
]


def _screening_actor(org):  # type: ignore[no-untyped-def]
    """An actor with the permissions and campaign assignment needed to run screening
    (which now also advances the application disposition via the TransitionService)."""
    return AuthenticatedActor(
        user_id=uuid.uuid4(),
        organisation_id=org.id,
        email="screener@example.com",
        role_names=["recruiter"],
        permissions={Permission.SCREENING_EXECUTE.value, Permission.APPLICATION_REVIEW.value},
        assigned_campaign_ids={CAMPAIGN},
    )


def _make_application(db_session, org, answers):  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id, campaign_id=CAMPAIGN, candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(), answers=answers,
        state=ApplicationState.EXTRACTION_REVIEW.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def _approved_rule_set(db_session, org):  # type: ignore[no-untyped-def]
    version = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="rs",
        rules=RULES, actor_id=uuid.uuid4(),
    )
    return rules_service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=version.id, approver_id=uuid.uuid4(),
    )


def _threshold(db_session, org):  # type: ignore[no-untyped-def]
    return rules_service.change_threshold(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN,
        review_below=40, recommend_at_or_above=70, change_reason="init",
        actor_id=uuid.uuid4(), approver_id=uuid.uuid4(),
    )


def test_screening_produces_explainable_reproducible_run(db_session) -> None:
    org = make_org(db_session)
    app = _make_application(db_session, org,
                            {"total_experience_years": "5", "current_location": "Remote"})
    # Verified Linux skill evidence.
    db_session.add(ExtractedField(
        organisation_id=org.id, application_id=app.id, field_name="skill_linux",
        extracted_value="linux", verified_value="linux",
        status=VerificationStatus.VERIFIED.value, extraction_method="manual", confidence=1.0,
    ))
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    result = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold,
        actor=_screening_actor(org),
    )
    run = result.run
    # Explainable: a result per criterion with evidence + awarded/max + reason (AC-09).
    assert len(run.results) == len(RULES)
    exp_result = next(r for r in run.results if r.criterion_name == "Total experience")
    assert exp_result.outcome == "pass"
    assert exp_result.awarded_score == 40
    assert exp_result.reason
    # Reproducibility fingerprint recorded (AC-08).
    assert run.input_data_hash
    assert run.engine_version


def test_missing_mandatory_evidence_does_not_auto_reject(db_session) -> None:
    # AC-10: no total_experience -> mandatory routes to review, not rejection.
    org = make_org(db_session)
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    result = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold,
        actor=_screening_actor(org),
    )
    run = result.run
    assert run.manual_review_required is True
    assert run.recommendation == "additional_information_required"
    # A review item was opened for the missing mandatory criterion.
    items = db_session.query(ReviewItem).filter_by(application_id=app.id).all()
    assert any(i.reason == "missing_mandatory_evidence" for i in items)


def test_reevaluation_preserves_original_run(db_session) -> None:
    # AC-13: re-evaluation creates a NEW run; the original is retained unchanged.
    org = make_org(db_session)
    app = _make_application(db_session, org,
                            {"total_experience_years": "5", "current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    actor = _screening_actor(org)
    first = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold, actor=actor,
    ).run
    first_id = first.id
    first_hash = first.input_data_hash

    second = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold, actor=actor,
    ).run

    assert second.id != first_id
    # Both runs still exist; original untouched.
    runs = db_session.query(ScreeningRun).filter_by(application_id=app.id).all()
    assert len(runs) == 2
    original = db_session.get(ScreeningRun, first_id)
    assert original is not None
    assert original.input_data_hash == first_hash
    # Deterministic: identical inputs -> identical hash and score.
    assert second.input_data_hash == first_hash
    assert second.score == first.score


def test_reevaluation_does_not_duplicate_open_review_items(db_session) -> None:
    # Re-running screening must NOT accumulate stale rows in the Review Queue: the prior
    # run's open items are superseded, leaving only the latest run's findings open. The
    # old items are retained (status SUPERSEDED) for audit, not deleted.
    org = make_org(db_session)
    # Missing mandatory experience -> routes to review on every run.
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)
    actor = _screening_actor(org)

    first = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold, actor=actor,
    ).run
    first_open = (
        db_session.query(ReviewItem)
        .filter_by(application_id=app.id, status="open")
        .all()
    )
    assert len(first_open) >= 1

    second = screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold, actor=actor,
    ).run
    assert second.id != first.id

    open_items = (
        db_session.query(ReviewItem)
        .filter_by(application_id=app.id, status="open")
        .all()
    )
    # Every remaining OPEN item belongs to the latest run only — no accumulation.
    assert open_items
    assert {i.screening_run_id for i in open_items} == {second.id}
    assert len(open_items) == len(first_open)
    # The first run's items are retained but closed as superseded (not deleted, not resolved).
    superseded = (
        db_session.query(ReviewItem)
        .filter_by(application_id=app.id, status="superseded", screening_run_id=first.id)
        .all()
    )
    assert len(superseded) == len(first_open)


def test_reevaluation_keeps_resolved_review_items(db_session) -> None:
    # A reviewer-RESOLVED item must survive a re-screen (its human decision is history);
    # only still-OPEN items from the prior run are superseded.
    org = make_org(db_session)
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)
    actor = _screening_actor(org)

    screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold, actor=actor,
    )
    item = db_session.query(ReviewItem).filter_by(application_id=app.id).first()
    assert item is not None
    review_service.record_action(
        db_session, organisation_id=org.id, review_item_id=item.id,
        action_type=ReviewActionType.CORRECT_VALUE, reason="confirmed from certificate",
        actor=actor, original_value="(none)", corrected_value="5", resolves_item=True,
    )
    db_session.refresh(item)
    assert item.status == "resolved"

    screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold, actor=actor,
    )
    db_session.refresh(item)
    # The resolved item is untouched by re-screening.
    assert item.status == "resolved"


def test_identical_inputs_give_identical_scores(db_session) -> None:
    org = make_org(db_session)
    answers = {"total_experience_years": "4", "current_location": "Remote"}
    app1 = _make_application(db_session, org, answers)
    app2 = _make_application(db_session, org, dict(answers))
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    r1 = screening_service.run_screening(
        db_session, application=app1, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    ).run
    r2 = screening_service.run_screening(
        db_session, application=app2, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    ).run
    assert r1.score == r2.score
    assert r1.input_data_hash == r2.input_data_hash


def test_review_correction_preserves_original(db_session) -> None:
    # Req 9.1: a correction records original + corrected value and a reason.
    org = make_org(db_session)
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)
    screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold,
        actor=_screening_actor(org),
    )
    item = db_session.query(ReviewItem).filter_by(application_id=app.id).first()
    assert item is not None

    action = review_service.record_action(
        db_session, organisation_id=org.id, review_item_id=item.id,
        action_type=ReviewActionType.CORRECT_VALUE, reason="confirmed from certificate",
        actor=_screening_actor(org), original_value="(none)", corrected_value="5",
        resolves_item=True,
    )
    assert action.original_value == "(none)"
    assert action.corrected_value == "5"
    stored = db_session.query(ReviewAction).filter_by(review_item_id=item.id).one()
    assert stored.reason == "confirmed from certificate"
    db_session.refresh(item)
    assert item.status == "resolved"


def _approver_actor(org):  # type: ignore[no-untyped-def]
    """A reviewer who also holds interview-approval authority (e.g. Recruiter Admin)."""
    return AuthenticatedActor(
        user_id=uuid.uuid4(),
        organisation_id=org.id,
        email="approver@example.com",
        role_names=["recruiter_admin"],
        permissions={
            Permission.APPLICATION_REVIEW.value,
            Permission.INTERVIEW_APPROVE.value,
            Permission.WAITLIST_MANAGE.value,
        },
        assigned_campaign_ids={CAMPAIGN},
    )


def _review_item_for(db_session, org):  # type: ignore[no-untyped-def]
    """Screen an application whose mandatory experience is missing so it routes to review,
    then return the application plus its open review item in MANUAL_REVIEW."""
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)
    screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold,
        actor=_screening_actor(org),
    )
    item = db_session.query(ReviewItem).filter_by(application_id=app.id).first()
    assert item is not None
    assert app.state == ApplicationState.MANUAL_REVIEW.value
    return app, item


def test_recommend_interview_from_review_advances_application(db_session) -> None:
    # A "select for interview" review action goes through the TransitionService and moves
    # the flagged candidate MANUAL_REVIEW -> INTERVIEW_RECOMMENDED (never a reject).
    org = make_org(db_session)
    app, item = _review_item_for(db_session, org)

    review_service.record_action(
        db_session, organisation_id=org.id, review_item_id=item.id,
        action_type=ReviewActionType.RECOMMEND_INTERVIEW,
        reason="strong profile, proceed to interview", actor=_approver_actor(org),
        resolves_item=True,
    )
    db_session.refresh(app)
    db_session.refresh(item)
    assert app.state == ApplicationState.INTERVIEW_RECOMMENDED.value
    assert item.status == "resolved"


def test_select_for_interview_clears_all_of_a_candidates_open_items(db_session) -> None:
    # A candidate with MULTIPLE flagged findings must leave the Review Queue entirely once
    # selected for interview — not keep reappearing because sibling items stayed open.
    org = make_org(db_session)
    # Missing BOTH mandatory experience AND the (optional, manual-review) linux skill, so
    # screening opens more than one review item for this one application.
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)
    screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold,
        actor=_screening_actor(org),
    )
    open_items = (
        db_session.query(ReviewItem).filter_by(application_id=app.id, status="open").all()
    )
    assert len(open_items) >= 2  # the bug only shows with multiple findings
    clicked = open_items[0]

    review_service.record_action(
        db_session, organisation_id=org.id, review_item_id=clicked.id,
        action_type=ReviewActionType.RECOMMEND_INTERVIEW,
        reason="strong profile overall", actor=_approver_actor(org), resolves_item=True,
    )
    db_session.refresh(app)
    assert app.state == ApplicationState.INTERVIEW_RECOMMENDED.value
    # No open items remain for this candidate -> she is gone from the queue.
    remaining_open = (
        db_session.query(ReviewItem).filter_by(application_id=app.id, status="open").all()
    )
    assert remaining_open == []
    # The clicked item is RESOLVED; its siblings are SUPERSEDED (closed by the disposition,
    # not individually acted on).
    db_session.refresh(clicked)
    assert clicked.status == "resolved"
    siblings = (
        db_session.query(ReviewItem)
        .filter(ReviewItem.application_id == app.id, ReviewItem.id != clicked.id)
        .all()
    )
    assert siblings
    assert all(s.status == "superseded" for s in siblings)


def test_request_info_does_not_close_sibling_items(db_session) -> None:
    # A non-disposition action ("Request info") is per-item: it must NOT close the
    # candidate's other open findings, since the candidate is not advanced.
    org = make_org(db_session)
    app = _make_application(db_session, org, {"current_location": "Remote"})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)
    screening_service.execute_for_application(
        db_session, organisation_id=org.id, application=app,
        rule_set_version=rule_version, threshold_version=threshold,
        actor=_screening_actor(org),
    )
    open_items = (
        db_session.query(ReviewItem).filter_by(application_id=app.id, status="open").all()
    )
    assert len(open_items) >= 2
    before = len(open_items)

    review_service.record_action(
        db_session, organisation_id=org.id, review_item_id=open_items[0].id,
        action_type=ReviewActionType.REQUEST_CLARIFICATION,
        reason="please send a transcript", actor=_approver_actor(org), resolves_item=False,
    )
    still_open = (
        db_session.query(ReviewItem).filter_by(application_id=app.id, status="open").all()
    )
    # Request-info advances to ADDITIONAL_INFO_REQUESTED and does not resolve items, so all
    # findings remain open for a human to work through.
    assert len(still_open) == before


def test_review_recommend_interview_requires_approval_authority(db_session) -> None:
    # Four-eyes: an author-only Recruiter (application.review but NOT interview.approve)
    # cannot advance a candidate to interview from the Review Queue. The TransitionService
    # rejects it and nothing is written.
    import pytest

    from app.core.errors import PermissionDeniedError

    org = make_org(db_session)
    app, item = _review_item_for(db_session, org)

    with pytest.raises(PermissionDeniedError):
        review_service.record_action(
            db_session, organisation_id=org.id, review_item_id=item.id,
            action_type=ReviewActionType.RECOMMEND_INTERVIEW,
            reason="try to self-approve", actor=_screening_actor(org),
            resolves_item=True,
        )
    db_session.refresh(app)
    db_session.refresh(item)
    assert app.state == ApplicationState.MANUAL_REVIEW.value
    assert item.status == "open"
    assert db_session.query(ReviewAction).filter_by(review_item_id=item.id).count() == 0


# --- Scoring denominator semantics (missing/unverifiable evidence != confirmed fail) -----


def test_manual_review_criteria_excluded_from_score_denominator(db_session) -> None:
    """A criterion routed to MANUAL_REVIEW must NOT drag the fit score down like a fail.

    Candidate confirms experience (mandatory, 40) and location (20) but the Linux skill
    (40, optional, missing_evidence=manual_review) cannot be verified -> routes to review.
    The score reflects only the DECIDABLE criteria (40+20 of 60 = 100.0); the unverifiable
    skill is excluded from BOTH numerator and denominator. The review flag is still set.
    """
    org = make_org(db_session)
    app = _make_application(
        db_session, org, {"total_experience_years": "5", "current_location": "Remote"}
    )
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    # No skill_linux evidence -> R-SKILL routes to manual_review.
    result = screening_service.run_screening(
        db_session, application=app, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    )
    run = result.run
    # Decidable criteria only: experience (40/40) + location (20/20) = 100.0.
    assert run.score == 100.0
    # ...but the unverifiable skill still forces human review (evidence != proof of absence).
    assert run.manual_review_required is True


def test_all_criteria_unverifiable_scores_zero_but_flags_review(db_session) -> None:
    """When EVERY criterion is undecidable the score is 0.0 but manual_review is set, so a
    0 here means 'nothing could be assessed', never a confirmed real-zero fit."""
    org = make_org(db_session)
    # No experience answer and no evidence -> experience + skill both route to review;
    # location has no evidence either -> fail (optional) contributes 0/20 decidable.
    app = _make_application(db_session, org, {})
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    result = screening_service.run_screening(
        db_session, application=app, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    )
    run = result.run
    assert run.manual_review_required is True
    # Location is the only decidable criterion (fails, 0/20) -> 0.0; the two review criteria
    # are excluded from the denominator rather than counted as zeros.
    assert run.score == 0.0


def test_score_is_deterministic_and_reproducible_after_denominator_change(db_session) -> None:
    """Same inputs + same rule version -> identical score and input hash (Req 8/AC-08)."""
    org = make_org(db_session)
    answers = {"total_experience_years": "5", "current_location": "Remote"}
    a1 = _make_application(db_session, org, answers)
    a2 = _make_application(db_session, org, dict(answers))
    rule_version = _approved_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    r1 = screening_service.run_screening(
        db_session, application=a1, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    ).run
    r2 = screening_service.run_screening(
        db_session, application=a2, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    ).run
    assert r1.score == r2.score
    assert r1.input_data_hash == r2.input_data_hash


# --- Walk-in candidate messaging (Section 9) ----------------------------------------------


def test_walk_in_message_below_boundary() -> None:
    msg = screening_service.walk_in_candidate_message(
        screening_ran=True, screening_failed=False, score=49.9,
        manual_review=False, conflict_flagged=False,
    )
    assert "HR team will get back to you" in msg
    assert "selected" not in msg.lower()


def test_walk_in_message_exactly_fifty_is_selected() -> None:
    # The boundary is inclusive: exactly 50% is "selected for the next stage".
    msg = screening_service.walk_in_candidate_message(
        screening_ran=True, screening_failed=False, score=50.0,
        manual_review=False, conflict_flagged=False,
    )
    assert "selected for the next stage" in msg


def test_walk_in_message_above_boundary_is_selected() -> None:
    msg = screening_service.walk_in_candidate_message(
        screening_ran=True, screening_failed=False, score=72.0,
        manual_review=False, conflict_flagged=False,
    )
    assert "selected for the next stage" in msg


def test_walk_in_message_high_score_but_manual_review_is_neutral() -> None:
    # >= 50% but needs review -> must NOT claim selection; neutral under-review message.
    msg = screening_service.walk_in_candidate_message(
        screening_ran=True, screening_failed=False, score=88.0,
        manual_review=True, conflict_flagged=False,
    )
    assert "being reviewed" in msg
    assert "selected" not in msg.lower()


def test_walk_in_message_data_conflict_is_neutral() -> None:
    msg = screening_service.walk_in_candidate_message(
        screening_ran=True, screening_failed=False, score=90.0,
        manual_review=False, conflict_flagged=True,
    )
    assert "being reviewed" in msg


def test_walk_in_message_screening_failure() -> None:
    # A failed scoring operation is never a real zero -> explicit "could not complete".
    msg = screening_service.walk_in_candidate_message(
        screening_ran=False, screening_failed=True, score=None,
        manual_review=False, conflict_flagged=False,
    )
    assert "could not be completed" in msg


def test_walk_in_message_no_rule_set_is_neutral_received() -> None:
    # No approved rule-set -> no definitive score message; neutral "received".
    msg = screening_service.walk_in_candidate_message(
        screening_ran=False, screening_failed=False, score=None,
        manual_review=False, conflict_flagged=False,
    )
    assert "has been received" in msg
    assert "selected" not in msg.lower()


# --- Default 50% progression threshold classification (49 / 50 / 51) ----------------------


def test_default_fifty_threshold_classifies_49_50_51(db_session) -> None:
    """With the default 50% threshold (review_below == recommend_at == 50): a score of 50 or
    above is RECOMMENDED (qualifies); 49 is below (does not). Exactly 50 qualifies.
    Exercises the real _derive_outcome used by run_screening, so the same scale (0-100) and
    comparison apply."""
    from app.modules.screening.models import ScreeningRecommendation
    from app.modules.screening.service import _derive_outcome

    def classify(score: float):  # type: ignore[no-untyped-def]
        _elig, _conf, rec, _manual = _derive_outcome(
            mandatory_failed=[], mandatory_review=[], any_review=False,
            score=score, review_below=50.0, recommend_at=50.0,
        )
        return rec

    recommended = ScreeningRecommendation.RECOMMENDED_FOR_INTERVIEW_REVIEW
    # Below 50 -> not qualified (waitlist/review).
    assert classify(49.0) is ScreeningRecommendation.WAITLIST_REVIEW
    # Exactly 50 qualifies; above 50 qualifies.
    assert classify(50.0) is recommended
    assert classify(51.0) is recommended


# --- JD-derived optional-skill scoring: honest weighted score (not 0, not 100) -----------

def _jd_optional_rule_set(db_session, org):  # type: ignore[no-untyped-def]
    """An approved rule-set built EXACTLY as a JD's desirable skills would generate it (five
    good-to-have skills, each weight 10, missing_evidence=fail). This is what real campaigns
    screen against, so the test exercises the production rule shape."""
    rules = rules_service.build_skill_rules_from_jd(
        mandatory_skills=[],
        desirable_skills=["React", "Docker", "Kubernetes", "GraphQL", "Redis"],
    )
    version = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="jd-rs",
        rules=rules, actor_id=uuid.uuid4(),
    )
    return rules_service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=version.id, approver_id=uuid.uuid4(),
    )


def _verified_skill(org, app, skill_id):  # type: ignore[no-untyped-def]
    return ExtractedField(
        organisation_id=org.id, application_id=app.id, field_name=f"skill:{skill_id}",
        extracted_value="present", verified_value=skill_id, extraction_method="test",
        status=VerificationStatus.VERIFIED.value, confidence=1.0,
    )


def test_partial_optional_skills_give_proportional_score_not_100(db_session) -> None:
    """A candidate who demonstrates 2 of the JD's 5 desirable skills must score ~40% on
    skills — NOT 100% (which the earlier 'exclude misses from the denominator' bug produced)
    and NOT 0%. Optional misses stay in the denominator and simply earn no points."""
    org = make_org(db_session)
    app = _make_application(db_session, org, {})
    fields = [_verified_skill(org, app, "react"), _verified_skill(org, app, "docker")]
    for f in fields:
        db_session.add(f)
    db_session.flush()
    rule_version = _jd_optional_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    run = screening_service.run_screening(
        db_session, application=app, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=fields,
    ).run
    # 2 of 5 skills confirmed, each weight 10 -> 20 of 50 -> 40.0.
    assert run.score == 40.0


def test_all_optional_skills_missing_scores_zero_not_hundred(db_session) -> None:
    """A candidate who demonstrates NONE of the JD's desirable skills scores 0% on skills —
    every optional skill is a decidable FAIL (0 of its weight), all staying in the
    denominator. This is the direct guard against the 'every resume got 100' regression."""
    org = make_org(db_session)
    app = _make_application(db_session, org, {})
    rule_version = _jd_optional_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    run = screening_service.run_screening(
        db_session, application=app, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=[],
    ).run
    assert run.score == 0.0


def test_all_optional_skills_present_scores_hundred(db_session) -> None:
    """A candidate who demonstrates ALL of the JD's desirable skills scores 100%."""
    org = make_org(db_session)
    app = _make_application(db_session, org, {})
    fields = [
        _verified_skill(org, app, s)
        for s in ("react", "docker", "kubernetes", "graphql", "redis")
    ]
    for f in fields:
        db_session.add(f)
    db_session.flush()
    rule_version = _jd_optional_rule_set(db_session, org)
    threshold = _threshold(db_session, org)

    run = screening_service.run_screening(
        db_session, application=app, rule_set_version=rule_version,
        threshold_version=threshold, extracted_fields=fields,
    ).run
    assert run.score == 100.0
