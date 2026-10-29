"""Tests for the campaign closure-readiness advisory (Req 3: warn HR if candidates or
interviews are still pending before completing/cancelling a campaign).

The readiness check is READ-ONLY and never blocks a transition — these tests assert the
counts it reports, not any gating behaviour.

All data here is clearly SYNTHETIC (testing.md: no real candidate information).
"""

from __future__ import annotations

import uuid

from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.campaigns import service as campaign_service
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.interviews.models import AttendanceStatus, InterviewInvitation
from tests.factories import make_org


def _campaign(db_session, org):  # type: ignore[no-untyped-def]
    campaign = Campaign(
        organisation_id=org.id,
        project_id=uuid.uuid4(),
        name="SYNTHETIC Campaign",
        position_title="Synthetic Engineer",
        number_of_openings=1,
        state=CampaignState.SELECTION_REVIEW.value,
        privacy_notice_version="v1",
    )
    db_session.add(campaign)
    db_session.flush()
    return campaign


def _application(db_session, org, campaign, state):  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id,
        campaign_id=campaign.id,
        candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(),
        answers={"full_name": "SYNTHETIC Candidate"},
        state=state.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def _invitation(db_session, org, campaign, app, attendance):  # type: ignore[no-untyped-def]
    import datetime as dt

    inv = InterviewInvitation(
        organisation_id=org.id,
        application_id=app.id,
        campaign_id=campaign.id,
        attendance=attendance.value,
        approved_by=uuid.uuid4(),
        invited_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(inv)
    db_session.flush()
    return inv


def test_no_pending_when_everything_is_final(db_session) -> None:
    org = make_org(db_session)
    campaign = _campaign(db_session, org)
    _application(db_session, org, campaign, ApplicationState.SELECTED)
    _application(db_session, org, campaign, ApplicationState.REJECTED)
    _application(db_session, org, campaign, ApplicationState.WITHDRAWN)

    readiness = campaign_service.closure_readiness(
        db_session, organisation_id=org.id, campaign_id=campaign.id
    )
    assert readiness.pending_applications == 0
    assert readiness.pending_interviews == 0
    assert readiness.has_pending is False


def test_pending_applications_counted(db_session) -> None:
    org = make_org(db_session)
    campaign = _campaign(db_session, org)
    # In-flight dispositions -> pending.
    _application(db_session, org, campaign, ApplicationState.SCREENED)
    _application(db_session, org, campaign, ApplicationState.INTERVIEW_SCHEDULED)
    # A final one -> not pending.
    _application(db_session, org, campaign, ApplicationState.SELECTED)

    readiness = campaign_service.closure_readiness(
        db_session, organisation_id=org.id, campaign_id=campaign.id
    )
    assert readiness.pending_applications == 2
    assert readiness.has_pending is True


def test_pending_interviews_counted(db_session) -> None:
    org = make_org(db_session)
    campaign = _campaign(db_session, org)
    app = _application(db_session, org, campaign, ApplicationState.INTERVIEW_SCHEDULED)
    # Not concluded -> pending.
    _invitation(db_session, org, campaign, app, AttendanceStatus.PENDING)
    # Concluded -> not pending.
    app2 = _application(db_session, org, campaign, ApplicationState.CHECKED_OUT)
    _invitation(db_session, org, campaign, app2, AttendanceStatus.CHECKED_OUT)

    readiness = campaign_service.closure_readiness(
        db_session, organisation_id=org.id, campaign_id=campaign.id
    )
    assert readiness.pending_interviews == 1
    assert readiness.has_pending is True


def test_readiness_is_scoped_to_the_campaign(db_session) -> None:
    org = make_org(db_session)
    target = _campaign(db_session, org)
    other = _campaign(db_session, org)
    # Pending work on the OTHER campaign must not leak into the target's counts.
    _application(db_session, org, other, ApplicationState.SCREENED)

    readiness = campaign_service.closure_readiness(
        db_session, organisation_id=org.id, campaign_id=target.id
    )
    assert readiness.pending_applications == 0
    assert readiness.has_pending is False
