"""Tests for the campaign state machine + TransitionService (Req 2.3, AC-04)."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import InvalidTransitionError, PermissionDeniedError
from app.modules.campaigns import service as campaign_service
from app.modules.campaigns.schemas import CampaignCreate
from app.modules.campaigns.states import CampaignState, allowed_destinations, find_transition
from app.modules.campaigns.transition_service import transition
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.projects import service as project_service
from app.modules.projects.schemas import ProjectCreate
from tests.factories import make_org, make_role, make_user


def _actor_for(user, campaign_ids, permissions):  # type: ignore[no-untyped-def]
    return AuthenticatedActor(
        user_id=user.id,
        organisation_id=user.organisation_id,
        email=user.email,
        role_names=["hr_head"],
        permissions=permissions,
        assigned_campaign_ids=set(campaign_ids),
    )


def _hr_head_perms() -> set[str]:
    from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS

    return {p.value for p in DEFAULT_ROLE_PERMISSIONS[RoleName.RECRUITER_ADMIN]}


def _seed_campaign(db_session):  # type: ignore[no-untyped-def]
    org = make_org(db_session)
    role = make_role(db_session, org, RoleName.RECRUITER_ADMIN)
    user = make_user(db_session, org, roles=[role])
    actor = _actor_for(user, set(), _hr_head_perms())
    project = project_service.create_project(
        db_session, org.id, ProjectCreate(name="SYNTHETIC Project"), actor.user_id
    )
    campaign = campaign_service.create_campaign(
        db_session,
        org.id,
        CampaignCreate(project_id=project.id, name="SYNTHETIC Campaign",
                       position_title="Synthetic Engineer"),
        actor.user_id,
    )
    # Reload assignment set so the actor is authorised on the created campaign.
    assigned = {
        row.campaign_id
        for row in db_session.query(CampaignAssignment).filter_by(user_id=user.id).all()
    }
    return org, user, _actor_for(user, assigned, _hr_head_perms()), campaign


def test_transition_table_is_well_formed() -> None:
    # Every destination reachable from DRAFT is a valid CampaignState.
    for dest in allowed_destinations(CampaignState.DRAFT):
        assert isinstance(dest, CampaignState)
    assert find_transition(CampaignState.DRAFT, CampaignState.PUBLISHED) is None


def test_invalid_transition_is_rejected(db_session) -> None:
    _, _, actor, campaign = _seed_campaign(db_session)
    # Draft -> Published is not a defined transition.
    with pytest.raises(InvalidTransitionError):
        transition(db_session, actor=actor, campaign=campaign,
                   destination=CampaignState.PUBLISHED, reason="skip ahead")


def test_cancel_from_draft_is_allowed(db_session) -> None:
    _, _, actor, campaign = _seed_campaign(db_session)
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.CANCELLED, reason="no longer needed")
    assert campaign.state == CampaignState.CANCELLED.value


def test_publication_blocked_without_prerequisites(db_session) -> None:
    # AC-04: cannot approve/publish without JD + rules + form + threshold + privacy notice.
    _, _, actor, campaign = _seed_campaign(db_session)
    campaign.state = CampaignState.APPROVAL_PENDING.value
    db_session.flush()
    with pytest.raises(InvalidTransitionError, match="missing prerequisites"):
        transition(db_session, actor=actor, campaign=campaign,
                   destination=CampaignState.APPROVED, reason="approve")


def test_approval_succeeds_with_all_prerequisites(db_session) -> None:
    # AC-04: with all prerequisites present, approval then publication succeed.
    _, _, actor, campaign = _seed_campaign(db_session)
    campaign.state = CampaignState.APPROVAL_PENDING.value
    campaign.approved_jd_version_id = uuid.uuid4()
    campaign.approved_rule_set_version_id = uuid.uuid4()
    campaign.approved_form_version_id = uuid.uuid4()
    campaign.active_threshold_version_id = uuid.uuid4()
    campaign.privacy_notice_version = "v1"
    db_session.flush()

    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.APPROVED, reason="all artifacts approved")
    assert campaign.state == CampaignState.APPROVED.value
    assert campaign.approved_by == actor.user_id

    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.PUBLISHED, reason="go live")
    assert campaign.state == CampaignState.PUBLISHED.value
    assert campaign.published_by == actor.user_id


def test_object_level_authz_blocks_unassigned_actor(db_session) -> None:
    _, user, _, campaign = _seed_campaign(db_session)
    # An actor with the permission but NOT assigned to this campaign is denied.
    outsider = _actor_for(user, set(), _hr_head_perms())  # empty assigned set
    with pytest.raises(PermissionDeniedError):
        transition(db_session, actor=outsider, campaign=campaign,
                   destination=CampaignState.CANCELLED, reason="x")
