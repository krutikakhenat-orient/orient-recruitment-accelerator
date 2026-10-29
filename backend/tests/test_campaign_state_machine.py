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


def _drive(db_session, actor, campaign, *states):  # type: ignore[no-untyped-def]
    """Set the campaign to a state directly (bypassing prerequisites) for lifecycle tests
    that only care about the close/pause/complete/cancel/reopen edges, not the artifact
    gates (those are covered by the prerequisite tests above)."""
    for s in states:
        campaign.state = s.value
    db_session.flush()


def test_close_applications_then_continue_screening(db_session) -> None:
    # Req 1: closing applications is a valid transition and the pipeline continues from it.
    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, CampaignState.APPLICATIONS_OPEN)
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.APPLICATIONS_CLOSED, reason="intake window over")
    assert campaign.state == CampaignState.APPLICATIONS_CLOSED.value
    # Screening can still begin on the already-collected candidates.
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.SCREENING, reason="begin screening")
    assert campaign.state == CampaignState.SCREENING.value


def test_pause_and_resume_round_trip(db_session) -> None:
    # Req 2: pause then resume returns to applications_open.
    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, CampaignState.APPLICATIONS_OPEN)
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.PAUSED, reason="hiring freeze")
    assert campaign.state == CampaignState.PAUSED.value
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.APPLICATIONS_OPEN, reason="freeze lifted")
    assert campaign.state == CampaignState.APPLICATIONS_OPEN.value


def test_complete_then_close_then_reopen(db_session) -> None:
    # Req 3 + 4: complete -> close, then an authorised user reopens the closed campaign.
    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, CampaignState.SELECTION_REVIEW)
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.COMPLETED, reason="all offers made")
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.CLOSED, reason="hiring finished")
    assert campaign.state == CampaignState.CLOSED.value
    # Reopen re-admits candidates (needs campaign.publish, which recruiter_admin holds).
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.APPLICATIONS_OPEN, reason="headcount reopened")
    assert campaign.state == CampaignState.APPLICATIONS_OPEN.value


def test_archived_is_terminal(db_session) -> None:
    # Req 4: archived has no outward transition (deliberately final).
    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, CampaignState.ARCHIVED)
    assert allowed_destinations(CampaignState.ARCHIVED) == []
    with pytest.raises(InvalidTransitionError):
        transition(db_session, actor=actor, campaign=campaign,
                   destination=CampaignState.APPLICATIONS_OPEN, reason="cannot reopen archived")


@pytest.mark.parametrize(
    "mid",
    [
        CampaignState.APPLICATIONS_OPEN,
        CampaignState.APPLICATIONS_CLOSED,
        CampaignState.SCREENING,
        CampaignState.HUMAN_REVIEW,
        CampaignState.INTERVIEW_PLANNING,
        CampaignState.INTERVIEWING,
        CampaignState.SELECTION_REVIEW,
        CampaignState.PAUSED,
    ],
)
def test_cancel_allowed_from_mid_pipeline_states(db_session, mid) -> None:
    # Req 3: a role dropped partway can be cancelled from any pre-completion operational
    # state. Parametrised so each case runs on a fresh session/campaign (cancel is terminal).
    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, mid)
    transition(db_session, actor=actor, campaign=campaign,
               destination=CampaignState.CANCELLED, reason="role withdrawn")
    assert campaign.state == CampaignState.CANCELLED.value


def test_cannot_cancel_a_completed_campaign(db_session) -> None:
    # Completed is finished, not abandoned: cancel is not a valid move from it (use close).
    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, CampaignState.COMPLETED)
    with pytest.raises(InvalidTransitionError):
        transition(db_session, actor=actor, campaign=campaign,
                   destination=CampaignState.CANCELLED, reason="x")


def test_transition_requires_reason(db_session) -> None:
    # Req 5: every lifecycle transition records a reason; a blank one is rejected.
    from app.core.errors import ValidationError

    _, _, actor, campaign = _seed_campaign(db_session)
    _drive(db_session, actor, campaign, CampaignState.APPLICATIONS_OPEN)
    with pytest.raises(ValidationError, match="reason"):
        transition(db_session, actor=actor, campaign=campaign,
                   destination=CampaignState.PAUSED, reason="   ")
