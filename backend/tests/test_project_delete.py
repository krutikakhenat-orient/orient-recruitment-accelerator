"""Tests for project edit + cascade delete (delete a project and all data inside it).

All data is synthetic.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.assessments.models import Assessment
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.interviews.models import AttendanceStatus, InterviewInvitation
from app.modules.projects import service as project_service
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from tests.factories import make_org

ACTOR = uuid.uuid4()


def _project(db_session, org, name="SYNTHETIC Project") -> Project:  # type: ignore[no-untyped-def]
    return project_service.create_project(
        db_session, org.id, ProjectCreate(name=name), ACTOR
    )


def _campaign(db_session, org, project_id) -> Campaign:  # type: ignore[no-untyped-def]
    c = Campaign(
        organisation_id=org.id, project_id=project_id, name="SYNTHETIC Campaign",
        position_title="Synthetic Engineer", number_of_openings=1,
        state=CampaignState.DRAFT.value,
    )
    db_session.add(c)
    db_session.flush()
    return c


def _application(db_session, org, campaign_id) -> Application:  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id, campaign_id=campaign_id, candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(), answers={"full_name": "SYNTHETIC Candidate"},
        state=ApplicationState.CHECKED_OUT.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


# --- Edit --------------------------------------------------------------------------------

def test_update_project_changes_only_given_fields(db_session) -> None:
    org = make_org(db_session)
    p = _project(db_session, org, name="Original")
    updated = project_service.update_project(
        db_session, org.id, p.id, ProjectUpdate(name="Renamed", department="Engineering"),
        ACTOR,
    )
    assert updated.name == "Renamed"
    assert updated.department == "Engineering"
    # Untouched field stays as-is.
    assert updated.status == "active"


def test_update_project_rejects_bad_date_order(db_session) -> None:
    import datetime as dt

    org = make_org(db_session)
    p = _project(db_session, org)
    with pytest.raises(ValidationError, match="cannot be before"):
        project_service.update_project(
            db_session, org.id, p.id,
            ProjectUpdate(
                planned_hiring_start=dt.date(2026, 6, 1),
                planned_hiring_end=dt.date(2026, 5, 1),
            ),
            ACTOR,
        )


def test_update_project_other_org_is_not_found(db_session) -> None:
    org = make_org(db_session)
    other = make_org(db_session, name="OTHER Org")
    p = _project(db_session, org)
    with pytest.raises(NotFoundError):
        project_service.update_project(
            db_session, other.id, p.id, ProjectUpdate(name="x"), ACTOR
        )


# --- Cascade delete ----------------------------------------------------------------------

def test_delete_project_removes_all_campaigns_and_data(db_session) -> None:
    from sqlalchemy import func, select

    org = make_org(db_session)
    project = _project(db_session, org)
    campaign = _campaign(db_session, org, project.id)
    app = _application(db_session, org, campaign.id)

    # An interview invitation + an assessment scoped to the application.
    inv = InterviewInvitation(
        organisation_id=org.id, application_id=app.id, campaign_id=campaign.id,
        status="confirmed", attendance=AttendanceStatus.CHECKED_OUT.value,
        approved_by=ACTOR, invited_at=func.now(), auto_invite=False,
    )
    db_session.add(inv)
    assessment = Assessment(
        organisation_id=org.id, application_id=app.id, campaign_id=campaign.id,
        panel_member_id=ACTOR, criteria_scores={"technical": 4}, recommendation="proceed",
        conflict_declared=False,
    )
    db_session.add(assessment)
    db_session.flush()

    project_id, campaign_id, app_id = project.id, campaign.id, app.id
    campaigns_removed, applications_removed = project_service.delete_project(
        db_session, org.id, project.id, ACTOR
    )
    assert campaigns_removed == 1
    assert applications_removed == 1

    # The cascade uses bulk DELETEs with synchronize_session=False, so drop any cached
    # instances and re-query the database to assert the rows are truly gone.
    db_session.expire_all()

    def _count(model, column, value) -> int:  # type: ignore[no-untyped-def]
        return db_session.execute(
            select(func.count()).select_from(model).where(column == value)
        ).scalar_one()

    assert _count(Project, Project.id, project_id) == 0
    assert _count(Campaign, Campaign.id, campaign_id) == 0
    assert _count(Application, Application.id, app_id) == 0
    assert _count(InterviewInvitation, InterviewInvitation.application_id, app_id) == 0
    assert _count(Assessment, Assessment.application_id, app_id) == 0


def test_delete_empty_project_succeeds(db_session) -> None:
    org = make_org(db_session)
    project = _project(db_session, org)
    campaigns_removed, applications_removed = project_service.delete_project(
        db_session, org.id, project.id, ACTOR
    )
    assert campaigns_removed == 0
    assert applications_removed == 0
    assert db_session.get(Project, project.id) is None


def test_delete_project_does_not_touch_other_projects(db_session) -> None:
    org = make_org(db_session)
    keep = _project(db_session, org, name="Keep")
    keep_campaign = _campaign(db_session, org, keep.id)
    drop = _project(db_session, org, name="Drop")
    _campaign(db_session, org, drop.id)

    project_service.delete_project(db_session, org.id, drop.id, ACTOR)

    # The untouched project and its campaign survive.
    assert db_session.get(Project, keep.id) is not None
    assert db_session.get(Campaign, keep_campaign.id) is not None


def test_delete_project_other_org_is_not_found(db_session) -> None:
    org = make_org(db_session)
    other = make_org(db_session, name="OTHER Org")
    p = _project(db_session, org)
    with pytest.raises(NotFoundError):
        project_service.delete_project(db_session, other.id, p.id, ACTOR)
