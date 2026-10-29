"""Tests for the interview-day Check In / Assess / Check Out workflow.

Covers: check-in eligibility + duplicate prevention; assessment save/retrieve + single
submission; check-out eligibility (assessment-before-checkout) + timestamp persistence;
Recruiter Admin visibility after checkout; panel-member authorisation; and that existing
historical ATTENDED records still work. All data is synthetic.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.errors import ConflictError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.assessments import service as assessment_service
from app.modules.assessments.models import AssessmentRecommendation
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews import service as interview_service
from app.modules.interviews.models import AttendanceStatus, InterviewInvitation
from tests.factories import make_org

CAMPAIGN = uuid.uuid4()
# Stable panel-member user id so an interviewer assignment created in _scheduled matches the
# actor used to drive check-in/assess/check-out across these tests.
PANEL_USER_ID = uuid.uuid4()


def _admin(org) -> AuthenticatedActor:  # type: ignore[no-untyped-def]
    perms = {p.value for p in DEFAULT_ROLE_PERMISSIONS[RoleName.RECRUITER_ADMIN]}
    perms |= {"interview.approve", "interview.schedule", "assessment.submit"}
    return AuthenticatedActor(
        user_id=uuid.uuid4(), organisation_id=org.id, email="admin@example.com",
        role_names=[RoleName.RECRUITER_ADMIN.value], permissions=perms,
        assigned_campaign_ids={CAMPAIGN},
    )


def _panel(org) -> AuthenticatedActor:  # type: ignore[no-untyped-def]
    """A real Interview Panel member: ONLY assessment.submit. Not campaign-assigned (that is
    the recruiter/HR object-level link); interview access comes from an InterviewAssignment
    created in _scheduled for this stable PANEL_USER_ID."""
    return AuthenticatedActor(
        user_id=PANEL_USER_ID, organisation_id=org.id, email="panel@example.com",
        role_names=[RoleName.INTERVIEW_PANEL.value],
        permissions={"assessment.submit"}, assigned_campaign_ids=set(),
    )


def _assign_panel(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """Give the stable panel member an active interviewer assignment to CAMPAIGN so the new
    interviewer-isolation checks permit their interview-day actions."""
    from app.modules.interviews.models import InterviewAssignment

    db_session.add(InterviewAssignment(
        organisation_id=org.id, campaign_id=CAMPAIGN, stage_id=None,
        interviewer_id=PANEL_USER_ID, assigned_by=uuid.uuid4(), is_active=True,
    ))
    db_session.flush()


def _application(db_session, org, state: ApplicationState) -> Application:  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id, campaign_id=CAMPAIGN, candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(), answers={"full_name": "SYNTHETIC Candidate"},
        state=state.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def _scheduled(db_session, org, admin):  # type: ignore[no-untyped-def]
    app = _application(db_session, org, ApplicationState.SCREENED)
    inv = interview_service.approve_invitation(db_session, actor=admin, application=app)
    stage = interview_service.create_stage(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="Tech", sequence=1,
        actor_id=admin.user_id,
    )
    slot = interview_service.create_slot(
        db_session, organisation_id=org.id, stage_id=stage.id, slot_date=dt.date.today(),
        start_time="10:00", location="HQ", mode="in_person", capacity=5,
        actor_id=admin.user_id,
    )
    interview_service.assign_slot_and_confirm(
        db_session, actor=admin, invitation_id=inv.id, slot_id=slot.id
    )
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value
    _assign_panel(db_session, org)
    return app, inv


# --- Check In -------------------------------------------------------------------------

def test_check_in_moves_scheduled_to_checked_in_and_stamps_time(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)

    updated = interview_service.check_in(db_session, actor=_panel(org), invitation_id=inv.id)

    assert app.state == ApplicationState.CHECKED_IN.value
    assert updated.attendance == AttendanceStatus.CHECKED_IN.value
    assert updated.checked_in_at is not None
    # Checking in does NOT complete/attend the interview on its own.
    assert updated.checked_out_at is None


def test_check_in_is_idempotent_guarded_no_duplicate(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    interview_service.check_in(db_session, actor=_panel(org), invitation_id=inv.id)

    with pytest.raises(ConflictError, match="already been checked in"):
        interview_service.check_in(db_session, actor=_panel(org), invitation_id=inv.id)
    assert app.state == ApplicationState.CHECKED_IN.value


def test_check_in_rejected_when_not_scheduled(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    # An application that never reached INTERVIEW_SCHEDULED.
    app = _application(db_session, org, ApplicationState.SCREENED)
    inv = InterviewInvitation(
        organisation_id=org.id, application_id=app.id, campaign_id=CAMPAIGN,
        status="invited", attendance=AttendanceStatus.PENDING.value,
        approved_by=admin.user_id, invited_at=dt.datetime.now(tz=dt.UTC), auto_invite=False,
    )
    db_session.add(inv)
    db_session.flush()
    _assign_panel(db_session, org)  # assigned interviewer; the state guard is what rejects
    with pytest.raises(ConflictError, match="scheduled"):
        interview_service.check_in(db_session, actor=_panel(org), invitation_id=inv.id)


# --- Assessment save / retrieve / single-submission -----------------------------------

def test_assessment_can_be_submitted_after_check_in_and_retrieved(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)

    assessment_service.submit_assessment(
        db_session, actor=panel, application=app,
        criteria_scores={"technical": 4, "communication": 5},
        recommendation=AssessmentRecommendation.PROCEED,
        interview_notes="Strong candidate",
    )
    assert app.state == ApplicationState.ASSESSED.value

    saved = assessment_service.get_assessment(
        db_session, organisation_id=org.id, application_id=app.id,
        panel_member_id=panel.user_id,
    )
    assert saved is not None
    assert saved.criteria_scores == {"technical": 4, "communication": 5}
    assert saved.recommendation == "proceed"
    assert saved.interview_notes == "Strong candidate"


def test_duplicate_assessment_submission_is_rejected(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)
    assessment_service.submit_assessment(
        db_session, actor=panel, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    # The application is now ASSESSED; force it back to CHECKED_IN to prove the explicit
    # duplicate-submission guard (not just the state guard) blocks a second submission.
    app.state = ApplicationState.CHECKED_IN.value
    db_session.flush()
    with pytest.raises(ConflictError, match="already submitted an assessment"):
        assessment_service.submit_assessment(
            db_session, actor=panel, application=app, criteria_scores={"technical": 3},
            recommendation=AssessmentRecommendation.HOLD,
        )


# --- Check Out ------------------------------------------------------------------------

def test_check_out_requires_assessment_first(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)

    # Checked in but NOT assessed yet -> cannot check out.
    with pytest.raises(ConflictError, match="assessment must be submitted"):
        interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)
    assert app.state == ApplicationState.CHECKED_IN.value


def test_check_out_after_assessment_completes_interview_and_stamps_time(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)
    assessment_service.submit_assessment(
        db_session, actor=panel, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    assert app.state == ApplicationState.ASSESSED.value

    updated = interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)
    assert app.state == ApplicationState.CHECKED_OUT.value
    assert updated.attendance == AttendanceStatus.CHECKED_OUT.value
    assert updated.checked_out_at is not None


def test_check_out_cannot_be_done_before_check_in(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    with pytest.raises(ConflictError, match="not been checked in"):
        interview_service.check_out(db_session, actor=_panel(org), invitation_id=inv.id)
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value


def test_duplicate_check_out_is_rejected(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)
    assessment_service.submit_assessment(
        db_session, actor=panel, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)
    with pytest.raises(ConflictError, match="already been checked out"):
        interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)


# --- Panel worklist stages + Recruiter Admin visibility -------------------------------

def test_panel_worklist_stages_across_lifecycle(db_session) -> None:
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)

    def stage_for(application_id: uuid.UUID) -> str:
        work = assessment_service.panel_worklist(db_session, org.id, PANEL_USER_ID)
        return next(w["stage"] for w in work if w["application_id"] == application_id)

    assert stage_for(app.id) == "to_check_in"
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)
    assert stage_for(app.id) == "to_assess"
    assessment_service.submit_assessment(
        db_session, actor=panel, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    assert stage_for(app.id) == "to_check_out"
    interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)
    assert stage_for(app.id) == "completed"


def test_checked_in_candidate_distinct_from_completed_for_recruiter_admin(db_session) -> None:
    """A checked-in (in-progress) candidate must be distinguishable from a checked-out
    (completed) one. The application state is the source of truth the recruiter reads."""
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)

    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)
    assert app.state == ApplicationState.CHECKED_IN.value  # in progress, NOT completed

    assessment_service.submit_assessment(
        db_session, actor=panel, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)
    assert app.state == ApplicationState.CHECKED_OUT.value  # now completed/attended


def test_panel_member_can_check_in_and_out(db_session) -> None:
    """A real panel member (assessment.submit only, not campaign-assigned) can drive the
    whole check-in -> assess -> check-out lifecycle."""
    org = make_org(db_session)
    admin = _admin(org)
    app, inv = _scheduled(db_session, org, admin)
    panel = _panel(org)
    interview_service.check_in(db_session, actor=panel, invitation_id=inv.id)
    assessment_service.submit_assessment(
        db_session, actor=panel, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    interview_service.check_out(db_session, actor=panel, invitation_id=inv.id)
    assert app.state == ApplicationState.CHECKED_OUT.value


def test_legacy_attended_state_still_assessable(db_session) -> None:
    """Historical records in the legacy ATTENDED state remain assessable (no silent
    conversion of old data)."""
    org = make_org(db_session)
    app = _application(db_session, org, ApplicationState.ATTENDED)
    _assign_panel(db_session, org)  # the assessor must be an assigned interviewer
    assessment_service.submit_assessment(
        db_session, actor=_panel(org), application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    assert app.state == ApplicationState.ASSESSED.value
