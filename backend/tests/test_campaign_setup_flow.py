"""Tests for the HR setup checklist and the one-step "Open for applications" action.

All data is synthetic. The action must not bypass governance: every hop runs through the
TransitionService (permission + assignment + audit), the recruiter (no campaign.publish)
is refused, and missing artifacts produce a plain error naming the checklist step.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import PermissionDeniedError, ValidationError
from app.modules.audit.models import AuditEvent
from app.modules.campaigns import service as campaign_service
from app.modules.campaigns.schemas import CampaignCreate
from app.modules.campaigns.states import CampaignState
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.projects import service as project_service
from app.modules.projects.schemas import ProjectCreate
from tests.factories import make_org, make_role, make_user


def _actor(user, campaign_ids, role: RoleName) -> AuthenticatedActor:  # type: ignore[no-untyped-def]
    return AuthenticatedActor(
        user_id=user.id,
        organisation_id=user.organisation_id,
        email=user.email,
        role_names=[role.value],
        permissions={p.value for p in DEFAULT_ROLE_PERMISSIONS[role]},
        assigned_campaign_ids=set(campaign_ids),
    )


def _seed(db_session, role: RoleName = RoleName.RECRUITER_ADMIN):  # type: ignore[no-untyped-def]
    org = make_org(db_session)
    user = make_user(db_session, org, roles=[make_role(db_session, org, role)])
    project = project_service.create_project(
        db_session, org.id, ProjectCreate(name="SYNTHETIC Project"), user.id
    )
    campaign = campaign_service.create_campaign(
        db_session,
        org.id,
        CampaignCreate(project_id=project.id, name="SYNTHETIC Setup Campaign",
                       position_title="Synthetic Analyst"),
        user.id,
    )
    assigned = {
        row.campaign_id
        for row in db_session.query(CampaignAssignment).filter_by(user_id=user.id).all()
    }
    return _actor(user, assigned, role), campaign


def _mark_all_artifacts_approved(db_session, campaign) -> None:  # type: ignore[no-untyped-def]
    campaign.approved_jd_version_id = uuid.uuid4()
    campaign.approved_rule_set_version_id = uuid.uuid4()
    campaign.active_threshold_version_id = uuid.uuid4()
    campaign.approved_form_version_id = uuid.uuid4()
    db_session.flush()


def _steps(db_session, campaign) -> dict[str, str]:  # type: ignore[no-untyped-def]
    status = campaign_service.setup_status(db_session, campaign=campaign)
    return {s.key: s.status for s in status.steps}


def test_new_campaign_checklist_starts_at_upload(db_session) -> None:
    _, campaign = _seed(db_session)
    status = campaign_service.setup_status(db_session, campaign=campaign)
    assert status.next_step_key == "upload_jd"
    assert status.is_open is False
    steps = _steps(db_session, campaign)
    assert steps["upload_jd"] == "todo"
    assert steps["approve_jd"] == "waiting"
    assert steps["open"] == "waiting"


def test_checklist_points_to_open_once_artifacts_are_approved(db_session) -> None:
    _, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)
    status = campaign_service.setup_status(db_session, campaign=campaign)
    assert status.next_step_key == "open"
    assert _steps(db_session, campaign)["open"] == "todo"


def test_open_for_applications_walks_from_draft_and_audits(db_session) -> None:
    actor, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)

    campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)

    assert campaign.state == CampaignState.APPLICATIONS_OPEN.value
    assert campaign.privacy_notice_version == "v1"
    actions = {
        e.action
        for e in db_session.query(AuditEvent).filter_by(entity_id=str(campaign.id)).all()
    }
    assert "campaign.privacy_notice_attached" in actions
    assert "campaign.transition.campaign_published" in actions
    assert "campaign.transition.applications_opened" in actions
    status = campaign_service.setup_status(db_session, campaign=campaign)
    assert status.is_open is True
    assert status.next_step_key is None


def test_open_keeps_an_explicit_privacy_notice(db_session) -> None:
    actor, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)
    campaign.privacy_notice_version = "synthetic-v7"
    db_session.flush()
    campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)
    assert campaign.privacy_notice_version == "synthetic-v7"


def test_open_is_idempotent_when_already_open(db_session) -> None:
    actor, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)
    campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)
    campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)
    assert campaign.state == CampaignState.APPLICATIONS_OPEN.value


def test_missing_form_gives_plain_error_and_changes_nothing(db_session) -> None:
    actor, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)
    campaign.approved_form_version_id = None
    db_session.flush()
    with pytest.raises(ValidationError, match="application form"):
        campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)
    assert campaign.state == CampaignState.DRAFT.value
    assert campaign.privacy_notice_version is None


def test_missing_jd_names_the_jd_step(db_session) -> None:
    actor, campaign = _seed(db_session)
    with pytest.raises(ValidationError, match="job description"):
        campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)


def test_recruiter_without_publish_permission_is_refused(db_session) -> None:
    actor, campaign = _seed(db_session, role=RoleName.RECRUITER)
    _mark_all_artifacts_approved(db_session, campaign)
    with pytest.raises(PermissionDeniedError):
        campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)
    assert campaign.state == CampaignState.DRAFT.value


def test_unassigned_admin_is_refused(db_session) -> None:
    actor, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)
    outsider = actor.model_copy(update={"assigned_campaign_ids": set()})
    with pytest.raises(PermissionDeniedError):
        campaign_service.open_for_applications(db_session, actor=outsider, campaign=campaign)


def test_past_setup_campaign_is_not_walked(db_session) -> None:
    actor, campaign = _seed(db_session)
    _mark_all_artifacts_approved(db_session, campaign)
    campaign.state = CampaignState.PAUSED.value
    db_session.flush()
    with pytest.raises(ValidationError, match="past setup"):
        campaign_service.open_for_applications(db_session, actor=actor, campaign=campaign)
