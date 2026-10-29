"""Role-based interviewer assignment + strict interview-panel isolation.

Covers the assignment model/service/API and the worklist/interview-action isolation it
enforces. All data is synthetic and clearly marked. These tests exercise REAL authorisation
through the service/API layers (not mocked frontend checks).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.assessments import service as assessment_service
from app.modules.assessments.models import Assessment, AssessmentRecommendation
from app.modules.audit.models import AuditEvent
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.identity.models import User
from app.modules.identity.permissions import RoleName
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews import assignment_service
from app.modules.interviews.models import (
    AttendanceStatus,
    InterviewAssignment,
    InterviewInvitation,
    InterviewStage,
)
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"


# --------------------------------------------------------------------------------------
# Builders (service-level, direct on db_session)
# --------------------------------------------------------------------------------------
def _campaign(db: Session, org, *, title: str, name: str | None = None) -> Campaign:  # type: ignore[no-untyped-def]
    campaign = Campaign(
        organisation_id=org.id,
        project_id=uuid.uuid4(),
        name=name or title,
        position_title=title,
        number_of_openings=1,
        state=CampaignState.APPLICATIONS_OPEN.value,
        privacy_notice_version="v1",
    )
    db.add(campaign)
    db.flush()
    return campaign


def _panel_user(db: Session, org, *, email: str) -> User:  # type: ignore[no-untyped-def]
    role = (
        db.query(__import__("app.modules.identity.models", fromlist=["Role"]).Role)
        .filter_by(organisation_id=org.id, name=RoleName.INTERVIEW_PANEL.value)
        .one_or_none()
    )
    if role is None:
        role = make_role(db, org, RoleName.INTERVIEW_PANEL)
    return make_user(db, org, roles=[role], password=PASSWORD, email=email)


def _application(  # type: ignore[no-untyped-def]
    db: Session, org, campaign, *,
    state=ApplicationState.INTERVIEW_SCHEDULED, name="Synthetic Candidate",
) -> Application:
    app = Application(
        organisation_id=org.id,
        campaign_id=campaign.id,
        candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(),
        answers={"full_name": name},
        state=state.value,
    )
    db.add(app)
    db.flush()
    return app


def _invitation(db: Session, org, app, *, stage_id=None) -> InterviewInvitation:  # type: ignore[no-untyped-def]
    import datetime as dt

    inv = InterviewInvitation(
        organisation_id=org.id, application_id=app.id, campaign_id=app.campaign_id,
        stage_id=stage_id, status="confirmed", attendance=AttendanceStatus.PENDING.value,
        approved_by=uuid.uuid4(), invited_at=dt.datetime.now(tz=dt.UTC), auto_invite=False,
    )
    db.add(inv)
    db.flush()
    return inv


def _assign(  # type: ignore[no-untyped-def]
    db: Session, org, campaign, interviewer_id, *,
    stage_id=None, assigned_by=None, active=True,
) -> InterviewAssignment:
    a = InterviewAssignment(
        organisation_id=org.id, campaign_id=campaign.id, stage_id=stage_id,
        interviewer_id=interviewer_id, assigned_by=assigned_by or uuid.uuid4(),
        is_active=active,
    )
    db.add(a)
    db.flush()
    return a


def _panel_actor(org, user_id) -> AuthenticatedActor:  # type: ignore[no-untyped-def]
    return AuthenticatedActor(
        user_id=user_id, organisation_id=org.id, email="panel@example.com",
        role_names=[RoleName.INTERVIEW_PANEL.value],
        permissions={"assessment.submit"}, assigned_campaign_ids=set(),
    )


# --------------------------------------------------------------------------------------
# 1 + 2 + 9: three campaigns; an interviewer assigned to only one sees only that one
# --------------------------------------------------------------------------------------
def test_interviewer_sees_only_assigned_campaign_across_three_roles(db_session) -> None:
    org = make_org(db_session)
    net = _campaign(db_session, org, title="Network Security Operations")
    ai = _campaign(db_session, org, title="AI Engineer")
    desk = _campaign(db_session, org, title="Desktop Support")
    panel = _panel_user(db_session, org, email="only-net@example.com")

    for camp in (net, ai, desk):
        _application(db_session, org, camp, name=f"Cand {camp.position_title}")

    # Assigned to Network Security only.
    _assign(db_session, org, net, panel.id)

    work = assessment_service.panel_worklist(db_session, org.id, panel.id)
    seen_campaigns = {w["campaign_id"] for w in work}
    assert seen_campaigns == {net.id}
    assert ai.id not in seen_campaigns and desk.id not in seen_campaigns


def test_requesting_unassigned_campaign_bucket_returns_empty(db_session) -> None:
    org = make_org(db_session)
    net = _campaign(db_session, org, title="Network Security Operations")
    ai = _campaign(db_session, org, title="AI Engineer")
    panel = _panel_user(db_session, org, email="net2@example.com")
    _application(db_session, org, ai)
    _assign(db_session, org, net, panel.id)

    # Asking for the AI bucket (not assigned) yields nothing — no broadening.
    work = assessment_service.panel_worklist(db_session, org.id, panel.id, campaign_id=ai.id)
    assert work == []


# --------------------------------------------------------------------------------------
# 3 + 4 + 15: multiple interviewers, independent scorecards, history preserved
# --------------------------------------------------------------------------------------
def test_five_interviewers_assigned_and_independent_scorecards(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    app = _application(db_session, org, camp, state=ApplicationState.CHECKED_IN)

    interviewers = [
        _panel_user(db_session, org, email=f"iv{i}@example.com") for i in range(5)
    ]
    for iv in interviewers:
        _assign(db_session, org, camp, iv.id)

    # Each interviewer independently submits an assessment; none overwrites another.
    for i, iv in enumerate(interviewers):
        assessment_service.submit_assessment(
            db_session, actor=_panel_actor(org, iv.id), application=app,
            criteria_scores={"technical": i + 1},
            recommendation=AssessmentRecommendation.PROCEED,
        )
        # Re-fetch application (submit transitions it to ASSESSED after the first).
        db_session.refresh(app)
        if app.state == ApplicationState.ASSESSED.value:
            app.state = ApplicationState.CHECKED_IN.value  # allow the next assessor
            db_session.flush()

    rows = db_session.execute(
        select(Assessment).where(Assessment.application_id == app.id)
    ).scalars().all()
    assert len(rows) == 5
    assert {r.panel_member_id for r in rows} == {iv.id for iv in interviewers}
    # Distinct scores preserved (no overwrite).
    assert sorted(r.criteria_scores["technical"] for r in rows) == [1, 2, 3, 4, 5]


def test_removing_and_recreating_assignment_preserves_assessments(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="Desktop Support")
    app = _application(db_session, org, camp, state=ApplicationState.CHECKED_IN)
    iv = _panel_user(db_session, org, email="hist@example.com")
    a = _assign(db_session, org, camp, iv.id)

    assessment_service.submit_assessment(
        db_session, actor=_panel_actor(org, iv.id), application=app,
        criteria_scores={"technical": 4}, recommendation=AssessmentRecommendation.PROCEED,
    )
    before = db_session.execute(
        select(func.count()).select_from(Assessment).where(Assessment.application_id == app.id)
    ).scalar_one()
    assert before == 1

    # Remove (soft) then re-create the assignment.
    assignment_service.deactivate_assignment(
        db_session, organisation_id=org.id, assignment_id=a.id, actor_id=uuid.uuid4()
    )
    assignment_service.create_assignment(
        db_session, organisation_id=org.id, campaign_id=camp.id, interviewer_id=iv.id,
        stage_id=None, assigned_by=uuid.uuid4(),
    )
    after = db_session.execute(
        select(func.count()).select_from(Assessment).where(Assessment.application_id == app.id)
    ).scalar_one()
    assert after == 1  # the assessment survived the remove + recreate


# --------------------------------------------------------------------------------------
# 5 + 6: no assignment => empty; inactive assignment revokes access
# --------------------------------------------------------------------------------------
def test_no_assignment_yields_empty_worklist(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    _application(db_session, org, camp)
    panel = _panel_user(db_session, org, email="noassign@example.com")
    assert assessment_service.panel_worklist(db_session, org.id, panel.id) == []


def test_inactive_assignment_immediately_revokes_access(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    app = _application(db_session, org, camp)
    panel = _panel_user(db_session, org, email="revoke@example.com")
    a = _assign(db_session, org, camp, panel.id)

    assert len(assessment_service.panel_worklist(db_session, org.id, panel.id)) == 1

    assignment_service.deactivate_assignment(
        db_session, organisation_id=org.id, assignment_id=a.id, actor_id=uuid.uuid4()
    )
    # Next call: access revoked.
    assert assessment_service.panel_worklist(db_session, org.id, panel.id) == []
    # And an interview action is now denied.
    with pytest.raises(PermissionDeniedError):
        assessment_service.require_panel_assignment(
            db_session, actor=_panel_actor(org, panel.id), application=app
        )


# --------------------------------------------------------------------------------------
# 7: stage-specific assignment does not grant other stages
# --------------------------------------------------------------------------------------
def test_stage_specific_assignment_does_not_grant_other_stages(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    stage_tech = InterviewStage(
        organisation_id=org.id, campaign_id=camp.id, name="Technical", sequence=1
    )
    stage_hr = InterviewStage(
        organisation_id=org.id, campaign_id=camp.id, name="HR", sequence=2
    )
    db_session.add_all([stage_tech, stage_hr])
    db_session.flush()

    panel = _panel_user(db_session, org, email="stage@example.com")
    _assign(db_session, org, camp, panel.id, stage_id=stage_tech.id)

    # A candidate whose invitation is for the Technical stage -> visible.
    app_tech = _application(db_session, org, camp, name="Tech Candidate")
    _invitation(db_session, org, app_tech, stage_id=stage_tech.id)
    # A candidate whose invitation is for the HR stage -> NOT visible to a Technical-only
    # assignee.
    app_hr = _application(db_session, org, camp, name="HR Candidate")
    _invitation(db_session, org, app_hr, stage_id=stage_hr.id)

    work = assessment_service.panel_worklist(db_session, org.id, panel.id)
    work_ids = {w["application_id"] for w in work}
    assert app_tech.id in work_ids
    assert app_hr.id not in work_ids

    # The direct authorisation check agrees per stage.
    assert assessment_service.panel_member_may_view_candidate(
        db_session, organisation_id=org.id, interviewer_id=panel.id, application=app_tech
    )
    assert not assessment_service.panel_member_may_view_candidate(
        db_session, organisation_id=org.id, interviewer_id=panel.id, application=app_hr
    )


# --------------------------------------------------------------------------------------
# 9: identical display names remain isolated by UUID
# --------------------------------------------------------------------------------------
def test_identical_campaign_names_isolated_by_uuid(db_session) -> None:
    org = make_org(db_session)
    camp_a = _campaign(db_session, org, title="Engineer", name="Engineer")
    camp_b = _campaign(db_session, org, title="Engineer", name="Engineer")  # same display name
    assert camp_a.id != camp_b.id
    app_a = _application(db_session, org, camp_a, name="A")
    app_b = _application(db_session, org, camp_b, name="B")
    panel = _panel_user(db_session, org, email="dupname@example.com")
    _assign(db_session, org, camp_a, panel.id)

    work = assessment_service.panel_worklist(db_session, org.id, panel.id)
    ids = {w["application_id"] for w in work}
    assert app_a.id in ids
    assert app_b.id not in ids  # same name, different UUID -> isolated


# --------------------------------------------------------------------------------------
# 13: cross-organisation isolation
# --------------------------------------------------------------------------------------
def test_cross_org_interviewer_sees_nothing(db_session) -> None:
    org_a = make_org(db_session, name="SYNTHETIC Org A")
    org_b = make_org(db_session, name="SYNTHETIC Org B")
    camp_a = _campaign(db_session, org_a, title="AI Engineer")
    _application(db_session, org_a, camp_a)
    panel_b = _panel_user(db_session, org_b, email="orgb@example.com")
    # An assignment cannot even be created cross-org (campaign not in org B).
    with pytest.raises(NotFoundError):
        assignment_service.create_assignment(
            db_session, organisation_id=org_b.id, campaign_id=camp_a.id,
            interviewer_id=panel_b.id, stage_id=None, assigned_by=uuid.uuid4(),
        )
    # And the worklist for org B's interviewer never shows org A candidates.
    assert assessment_service.panel_worklist(db_session, org_b.id, panel_b.id) == []


# --------------------------------------------------------------------------------------
# 14: duplicate assignment handled safely (idempotent)
# --------------------------------------------------------------------------------------
def test_duplicate_assignment_is_idempotent(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    iv = _panel_user(db_session, org, email="dup@example.com")

    first = assignment_service.create_assignment(
        db_session, organisation_id=org.id, campaign_id=camp.id, interviewer_id=iv.id,
        stage_id=None, assigned_by=uuid.uuid4(),
    )
    second = assignment_service.create_assignment(
        db_session, organisation_id=org.id, campaign_id=camp.id, interviewer_id=iv.id,
        stage_id=None, assigned_by=uuid.uuid4(),
    )
    assert first.id == second.id  # same row, no duplicate
    count = db_session.execute(
        select(func.count()).select_from(InterviewAssignment).where(
            InterviewAssignment.campaign_id == camp.id,
            InterviewAssignment.interviewer_id == iv.id,
        )
    ).scalar_one()
    assert count == 1


def test_assigning_user_without_assessment_permission_rejected(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    # A recruiter (no assessment.submit) cannot be assigned as an interviewer.
    rec_role = make_role(db_session, org, RoleName.RECRUITER)
    rec = make_user(db_session, org, roles=[rec_role], password=PASSWORD, email="rec@example.com")
    with pytest.raises(ValidationError, match="interview-panel"):
        assignment_service.create_assignment(
            db_session, organisation_id=org.id, campaign_id=camp.id, interviewer_id=rec.id,
            stage_id=None, assigned_by=uuid.uuid4(),
        )


# --------------------------------------------------------------------------------------
# 16: audit events for assignment changes
# --------------------------------------------------------------------------------------
def test_assignment_changes_emit_audit_events(db_session) -> None:
    org = make_org(db_session)
    camp = _campaign(db_session, org, title="AI Engineer")
    iv = _panel_user(db_session, org, email="audit@example.com")

    a = assignment_service.create_assignment(
        db_session, organisation_id=org.id, campaign_id=camp.id, interviewer_id=iv.id,
        stage_id=None, assigned_by=uuid.uuid4(),
    )
    assignment_service.deactivate_assignment(
        db_session, organisation_id=org.id, assignment_id=a.id, actor_id=uuid.uuid4()
    )
    actions = set(
        db_session.execute(
            select(AuditEvent.action).where(AuditEvent.entity_id == str(a.id))
        ).scalars()
    )
    assert "interview.assignment_added" in actions
    assert "interview.assignment_removed" in actions
