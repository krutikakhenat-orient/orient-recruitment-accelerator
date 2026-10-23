"""Tests for application submission, extraction, and candidate/application separation.

Covers Req 5.1-5.4: public submission validates against the approved form, requires
privacy consent, snapshots answers, runs resume extraction, flags conflicts/safety issues
for manual review, and keeps application answers independent of the master candidate
profile. Also exercises the application state machine.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ConflictError, InvalidTransitionError, ValidationError
from app.modules.applications import service
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.applications.transition_service import transition
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.candidates.models import Candidate
from app.modules.forms import service as form_service
from tests.factories import make_org

RESUME = (
    b"Jane Synthetic\nemail: jane.synthetic@example.com\n"
    b"Phone: +1 415 555 0100\n6 years of experience.\n"
)

BASE_ANSWERS = {
    # "position_applied_for" is no longer a form field — the candidate selects the role
    # (campaign) instead, and the position title is filled in automatically on submit.
    "full_name": "Jane Synthetic",
    "email": "jane.synthetic@example.com",
    "mobile": "+14155550100",
    "current_location": "Mumbai",
    "total_experience_years": "6",
    "notice_period": "30 days",
    "skills": "Python, Linux",
    "education": "BSc",
    "candidate_declaration": True,
    "privacy_consent": True,
}


def _open_campaign_with_form(db_session, org, *, compensation=False):  # type: ignore[no-untyped-def]
    """Create a campaign with an approved form, moved to APPLICATIONS_OPEN."""
    campaign = Campaign(
        organisation_id=org.id,
        project_id=uuid.uuid4(),
        name="SYNTHETIC Campaign",
        position_title="Synthetic Engineer",
        number_of_openings=1,
        state=CampaignState.APPLICATIONS_OPEN.value,
        privacy_notice_version="v1",
    )
    db_session.add(campaign)
    db_session.flush()

    form = form_service.create_form_draft(
        db_session, organisation_id=org.id, campaign_id=campaign.id,
        actor_id=uuid.uuid4(), compensation_enabled=compensation,
    )
    form_service.approve_form_version(
        db_session, organisation_id=org.id, form_version_id=form.id, actor_id=uuid.uuid4()
    )
    campaign.approved_form_version_id = form.id
    db_session.flush()
    return campaign


def test_submit_application_happy_path(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id,
        answers=dict(BASE_ANSWERS), resume_filename="resume.txt",
        resume_content_type="text/plain", resume_bytes=RESUME,
    )
    assert result.application.state == ApplicationState.EXTRACTION_REVIEW.value
    assert result.candidate_created is True
    # Clean, matching data -> no manual review required.
    assert result.manual_review is False
    assert db_session.query(Candidate).count() == 1


def test_privacy_consent_required(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    answers = dict(BASE_ANSWERS, privacy_consent=False)
    with pytest.raises(ValidationError, match="Privacy consent"):
        service.submit_application(
            db_session, organisation_id=org.id, campaign_id=campaign.id, answers=answers,
            resume_filename="r.txt", resume_content_type="text/plain", resume_bytes=RESUME,
        )


def test_prohibited_field_rejected(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    answers = dict(BASE_ANSWERS, date_of_birth="1990-01-01")
    with pytest.raises(ValidationError, match="not accepted"):
        service.submit_application(
            db_session, organisation_id=org.id, campaign_id=campaign.id, answers=answers,
            resume_filename="r.txt", resume_content_type="text/plain", resume_bytes=RESUME,
        )


def test_conflicting_resume_flags_manual_review(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    # Candidate-entered email differs from the email in the resume -> conflict.
    answers = dict(BASE_ANSWERS, email="different.email@example.com", full_name="Jane Other")
    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id, answers=answers,
        resume_filename="r.txt", resume_content_type="text/plain", resume_bytes=RESUME,
    )
    assert result.manual_review is True
    assert "email" in result.extraction_summary.conflicts


def test_duplicate_application_rejected(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id, answers=dict(BASE_ANSWERS),
        resume_filename="r.txt", resume_content_type="text/plain", resume_bytes=RESUME,
    )
    with pytest.raises(ConflictError, match="already exists"):
        service.submit_application(
            db_session, organisation_id=org.id, campaign_id=campaign.id,
            answers=dict(BASE_ANSWERS), resume_filename="r.txt",
            resume_content_type="text/plain", resume_bytes=RESUME,
        )


def test_closed_campaign_rejects_application(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    campaign.state = CampaignState.DRAFT.value
    db_session.flush()
    with pytest.raises(ConflictError, match="not currently accepting"):
        service.submit_application(
            db_session, organisation_id=org.id, campaign_id=campaign.id,
            answers=dict(BASE_ANSWERS), resume_filename="r.txt",
            resume_content_type="text/plain", resume_bytes=RESUME,
        )


def test_profile_edit_does_not_rewrite_application_answers(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id, answers=dict(BASE_ANSWERS),
        resume_filename="r.txt", resume_content_type="text/plain", resume_bytes=RESUME,
    )
    app_id = result.application.id
    candidate = db_session.query(Candidate).one()

    # Edit the master candidate profile.
    candidate.full_name = "Jane Renamed"
    candidate.mobile = "+10000000000"
    db_session.flush()

    stored = db_session.get(Application, app_id)
    # The application's snapshot is unchanged.
    assert stored.answers["full_name"] == "Jane Synthetic"
    assert stored.answers["mobile"] == "+14155550100"


def test_withdraw_transition_allowed_and_invalid_rejected(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id, answers=dict(BASE_ANSWERS),
        resume_filename="r.txt", resume_content_type="text/plain", resume_bytes=RESUME,
    )
    app = result.application
    # Candidate withdrawal from EXTRACTION_REVIEW is permitted (no actor needed).
    transition(db_session, application=app, destination=ApplicationState.WITHDRAWN,
               reason="candidate withdrew")
    assert app.state == ApplicationState.WITHDRAWN.value
    # A nonsensical transition is rejected.
    with pytest.raises(InvalidTransitionError):
        transition(db_session, application=app, destination=ApplicationState.SELECTED,
                   reason="x")


# --- Ranking within a campaign (by latest-run score desc, unscored last) ------------------


def _bare_application(db_session, org, campaign):  # type: ignore[no-untyped-def]
    """A minimal application row in a campaign (no screening yet)."""
    app = Application(
        organisation_id=org.id,
        campaign_id=campaign.id,
        candidate_id=uuid.uuid4(),
        form_version_id=campaign.approved_form_version_id,
        answers={"full_name": "Synthetic Candidate"},
        state=ApplicationState.SCREENED.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def _completed_run(db_session, org, app, score, started_at=None):  # type: ignore[no-untyped-def]
    """Attach a COMPLETED screening run with the given score to an application.

    ``started_at`` can be set explicitly so a test can make "latest" unambiguous rather
    than relying on same-tick ordering.
    """
    import datetime as dt

    from app.modules.screening.models import ScreeningRun

    run = ScreeningRun(
        organisation_id=org.id,
        application_id=app.id,
        rule_set_version_id=uuid.uuid4(),
        score=score,
        eligibility_outcome="eligible",
        confidence_status="confirmed",
        recommendation="recommended_for_interview_review",
        manual_review_required=False,
        completed_at=dt.datetime.now(tz=dt.UTC),
        input_data_hash="x" * 12,
        engine_version="1.0.0",
    )
    if started_at is not None:
        run.started_at = started_at
    db_session.add(run)
    db_session.flush()
    return run


def test_ranking_orders_by_score_desc_with_unscored_last(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)

    low = _bare_application(db_session, org, campaign)
    high = _bare_application(db_session, org, campaign)
    mid = _bare_application(db_session, org, campaign)
    never = _bare_application(db_session, org, campaign)  # no run -> unscored, last

    _completed_run(db_session, org, low, 30.0)
    _completed_run(db_session, org, high, 90.0)
    _completed_run(db_session, org, mid, 60.0)

    ranked = service.list_ranked_for_campaign(
        db_session, org.id, campaign.id, limit=100, offset=0
    )
    order = [r.application.id for r in ranked]
    assert order == [high.id, mid.id, low.id, never.id]
    # Ranks are 1-based over the scored candidates; the unscored one has rank None.
    by_id = {r.application.id: r for r in ranked}
    assert by_id[high.id].rank == 1 and by_id[high.id].score == 90.0
    assert by_id[mid.id].rank == 2
    assert by_id[low.id].rank == 3
    assert by_id[never.id].rank is None
    assert by_id[never.id].scored is False


def test_ranking_never_mixes_across_campaigns(db_session) -> None:
    org = make_org(db_session)
    c1 = _open_campaign_with_form(db_session, org)
    c2 = _open_campaign_with_form(db_session, org)

    a1 = _bare_application(db_session, org, c1)
    a2 = _bare_application(db_session, org, c2)
    _completed_run(db_session, org, a1, 40.0)
    _completed_run(db_session, org, a2, 95.0)  # higher, but a DIFFERENT campaign

    ranked_c1 = service.list_ranked_for_campaign(
        db_session, org.id, c1.id, limit=100, offset=0
    )
    ids = [r.application.id for r in ranked_c1]
    # c2's high scorer must not leak into c1's ranking.
    assert ids == [a1.id]
    assert ranked_c1[0].rank == 1


def test_ranking_uses_latest_run_deterministically(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app = _bare_application(db_session, org, campaign)

    # Two runs with explicit timestamps; the later one is unambiguously the latest and wins.
    import datetime as dt

    base = dt.datetime.now(tz=dt.UTC)
    _completed_run(db_session, org, app, 20.0, started_at=base)
    latest = _completed_run(
        db_session, org, app, 80.0, started_at=base + dt.timedelta(seconds=1)
    )

    ranked = service.list_ranked_for_campaign(
        db_session, org.id, campaign.id, limit=100, offset=0
    )
    assert len(ranked) == 1
    assert ranked[0].score == 80.0
    assert ranked[0].latest_run_id == latest.id


# --- Two-stage candidate-facing messages (initial + score-based; meeting requirement) -----


def test_submit_returns_initial_thank_you_message(db_session) -> None:
    """Stage 1: immediately after a successful submit, the candidate sees the fixed initial
    confirmation — NOT a score-based message (scoring result is fetched separately)."""
    from app.modules.screening.service import INITIAL_SUBMISSION_MESSAGE

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    # Echo what the public router returns to the candidate on submit.
    from app.modules.applications.schemas import SubmissionResponse

    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id,
        answers=dict(BASE_ANSWERS), resume_filename="r.txt",
        resume_content_type="text/plain", resume_bytes=RESUME,
    )
    response = SubmissionResponse(
        application_id=result.application.id,
        state=result.application.state,
        manual_review=result.manual_review,
        message=INITIAL_SUBMISSION_MESSAGE,
    )
    assert response.message == "Thank you for applying. Your application has been received."


def test_status_pending_before_scoring(db_session) -> None:
    """Stage 2 (pending): an application with no completed run keeps the initial message."""
    from app.modules.screening.service import INITIAL_SUBMISSION_MESSAGE

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app = _bare_application(db_session, org, campaign)  # no screening run

    status = service.public_application_status(db_session, org.id, app.id)
    assert status is not None
    assert status.status == "pending"
    assert status.message == INITIAL_SUBMISSION_MESSAGE


def test_status_scored_below_fifty(db_session) -> None:
    """Stage 2 (<50): the polite 'received, we'll be in touch' message."""
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app = _bare_application(db_session, org, campaign)
    _completed_run(db_session, org, app, 49.99)

    status = service.public_application_status(db_session, org.id, app.id)
    assert status is not None
    assert status.status == "scored"
    assert status.message == (
        "THANK YOU FOR YOUR TIME HR WILL GET BACK TO YOU YOU CAN LEAVE FOR THE DAY"
    )


def test_status_scored_fifty_or_above(db_session) -> None:
    """Stage 2 (>=50, strict boundary inclusive): the 'selected for next stage' message."""
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app = _bare_application(db_session, org, campaign)
    _completed_run(db_session, org, app, 50.0)

    status = service.public_application_status(db_session, org.id, app.id)
    assert status is not None
    assert status.status == "scored"
    assert status.message == (
        "Your CV has been selected for the next stage. Kindly contact the HR department for "
        "your second round of interview."
    )


def test_status_failed_scoring_is_not_a_zero(db_session) -> None:
    """A completed run that recorded a processing error is 'failed', never a real 0 score,
    so the candidate never sees an incorrect 'below 50' result."""
    import datetime as dt

    from app.modules.screening.models import ScreeningRun

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app = _bare_application(db_session, org, campaign)
    run = ScreeningRun(
        organisation_id=org.id, application_id=app.id, rule_set_version_id=uuid.uuid4(),
        score=0.0, eligibility_outcome="needs_review", confidence_status="needs_review",
        recommendation="low_extraction_confidence", manual_review_required=True,
        completed_at=dt.datetime.now(tz=dt.UTC), processing_errors="extraction failed",
        input_data_hash="x" * 12, engine_version="1.0.0",
    )
    db_session.add(run)
    db_session.flush()

    status = service.public_application_status(db_session, org.id, app.id)
    assert status is not None
    assert status.status == "failed"
    assert "could not be completed" in status.message
    # It must NOT be shown as a below-50 selection message.
    assert "selected for the next stage" not in status.message


def test_status_unknown_application_returns_none(db_session) -> None:
    """A non-existent application id resolves to None (router shows neutral pending)."""
    org = make_org(db_session)
    assert service.public_application_status(db_session, org.id, uuid.uuid4()) is None


# --- Auto-progression of eligible (>=50, clean) candidates into the Interview Panel -------


def _scored_app(db_session, org, campaign, score, *, manual=False, conflict=False):  # type: ignore[no-untyped-def]
    """A screened application with a completed run of the given score/flags."""
    import datetime as dt

    from app.modules.screening.models import ScreeningRun

    app = _bare_application(db_session, org, campaign)
    run = ScreeningRun(
        organisation_id=org.id, application_id=app.id, rule_set_version_id=uuid.uuid4(),
        score=score, eligibility_outcome="eligible", confidence_status="confirmed",
        recommendation="recommended_for_interview_review",
        manual_review_required=manual, conflict_flagged=conflict,
        completed_at=dt.datetime.now(tz=dt.UTC), input_data_hash="x" * 12,
        engine_version="1.0.0",
    )
    db_session.add(run)
    db_session.flush()
    return app, run


def _invitation_count(db_session, app):  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from app.modules.interviews.models import InterviewInvitation

    return db_session.execute(
        select(func.count()).select_from(InterviewInvitation)
        .where(InterviewInvitation.application_id == app.id)
    ).scalar_one()


def test_eligible_candidate_auto_progresses_to_interview_panel(db_session) -> None:
    """Score >= 50 and clean -> candidate reaches INTERVIEW_SCHEDULED and appears on the
    Interview Panel worklist, with exactly one invitation (no manual 'Select' click)."""
    from app.modules.assessments.service import panel_worklist
    from app.modules.screening import service as screening_service

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app, run = _scored_app(db_session, org, campaign, 75.0)

    progressed = screening_service.auto_progress_to_interview(
        db_session, organisation_id=org.id, application=app, run=run
    )
    assert progressed is True
    db_session.refresh(app)
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value
    assert _invitation_count(db_session, app) == 1
    # It shows up on the existing panel worklist. A freshly-scheduled candidate is awaiting
    # check-in in the interview-day flow (Scheduled -> Checked In -> Assessed -> Checked Out).
    worklist = panel_worklist(db_session, org.id)
    assert any(
        row["application_id"] == app.id and row["stage"] == "to_check_in" for row in worklist
    )


def test_auto_progression_is_idempotent_on_retry(db_session) -> None:
    """Re-running progression (e.g. a retried submit) must NOT create duplicate invitations."""
    from app.modules.screening import service as screening_service

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app, run = _scored_app(db_session, org, campaign, 88.0)

    screening_service.auto_progress_to_interview(
        db_session, organisation_id=org.id, application=app, run=run
    )
    # Second call (retry) — reuses the existing invitation / state.
    screening_service.auto_progress_to_interview(
        db_session, organisation_id=org.id, application=app, run=run
    )
    assert _invitation_count(db_session, app) == 1


def test_below_fifty_not_auto_progressed(db_session) -> None:
    from app.modules.screening import service as screening_service

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app, run = _scored_app(db_session, org, campaign, 49.0)

    progressed = screening_service.auto_progress_to_interview(
        db_session, organisation_id=org.id, application=app, run=run
    )
    assert progressed is False
    assert _invitation_count(db_session, app) == 0
    db_session.refresh(app)
    assert app.state == ApplicationState.SCREENED.value


def test_manual_review_candidate_keeps_safeguard_not_auto_progressed(db_session) -> None:
    """A >=50 candidate flagged for manual review must NOT be auto-progressed — the existing
    human-review safeguard is preserved."""
    from app.modules.screening import service as screening_service

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app, run = _scored_app(db_session, org, campaign, 92.0, manual=True)

    progressed = screening_service.auto_progress_to_interview(
        db_session, organisation_id=org.id, application=app, run=run
    )
    assert progressed is False
    assert _invitation_count(db_session, app) == 0


def test_conflict_candidate_not_auto_progressed(db_session) -> None:
    from app.modules.screening import service as screening_service

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    app, run = _scored_app(db_session, org, campaign, 92.0, conflict=True)

    progressed = screening_service.auto_progress_to_interview(
        db_session, organisation_id=org.id, application=app, run=run
    )
    assert progressed is False
    assert _invitation_count(db_session, app) == 0


# --- "Position applied for" removed + resume pre-fill (meeting request) --------------------


def test_new_form_has_no_position_applied_for_field(db_session) -> None:
    """New application forms must NOT include the redundant 'position applied for' field —
    the candidate selects the role (campaign) instead."""
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    _version, fields = service._load_form(db_session, campaign.approved_form_version_id)
    keys = {f.key for f in fields}
    assert "position_applied_for" not in keys


def test_submit_without_position_field_succeeds(db_session) -> None:
    """A candidate submits without any 'position applied for' answer and it still works."""
    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id,
        answers=dict(BASE_ANSWERS), resume_filename="r.txt",
        resume_content_type="text/plain", resume_bytes=RESUME,
    )
    assert result.application.state == ApplicationState.EXTRACTION_REVIEW.value
    # The candidate never supplied a position; nothing about the role was required of them.
    assert "position_applied_for" not in result.application.answers


def test_submit_autofills_legacy_position_field_from_campaign(db_session) -> None:
    """An EXISTING approved form that still contains 'position_applied_for' must keep working:
    the field is auto-filled from the campaign's position title, never required of the
    candidate."""
    from app.modules.forms.models import FieldClass, FormField

    org = make_org(db_session)
    campaign = _open_campaign_with_form(db_session, org)
    # Simulate a legacy form by adding the old required field to the approved form version.
    version, _fields = service._load_form(db_session, campaign.approved_form_version_id)
    version.fields.append(FormField(
        form_version_id=version.id, key="position_applied_for",
        label="Position applied for", field_class=FieldClass.CORE_IDENTITY.value,
        field_type="text", required=True, order_index=0,
    ))
    db_session.flush()

    result = service.submit_application(
        db_session, organisation_id=org.id, campaign_id=campaign.id,
        answers=dict(BASE_ANSWERS), resume_filename="r.txt",
        resume_content_type="text/plain", resume_bytes=RESUME,
    )
    # Auto-filled from the campaign's authoritative position title.
    assert result.application.answers["position_applied_for"] == campaign.position_title


def test_resume_preview_suggests_fields_from_resume(db_session) -> None:  # noqa: ARG001
    """The public resume-preview parses a resume and suggests form answers (email / mobile /
    experience) for the candidate to review — read-only, no persistence."""
    resume = (
        b"Alex Candidate\nEmail: alex.candidate@example.com\n"
        b"Phone: +1 415 555 0199\n7 years of experience in backend engineering.\n"
    )
    preview = service.preview_resume_fields(
        resume_filename="alex.txt", resume_content_type="text/plain", resume_bytes=resume,
    )
    assert preview.extracted is True
    assert preview.fields.get("email") == "alex.candidate@example.com"
    assert preview.fields.get("total_experience_years") == "7"
    # A position field is never suggested — the candidate picks the role.
    assert "position_applied_for" not in preview.fields


def test_resume_preview_unreadable_returns_not_extracted(db_session) -> None:  # noqa: ARG001
    """An empty/unreadable resume yields extracted=False and no suggestions (never a
    misleading pre-fill)."""
    preview = service.preview_resume_fields(
        resume_filename="empty.txt", resume_content_type="text/plain", resume_bytes=b"",
    )
    assert preview.extracted is False
    assert preview.fields == {}
