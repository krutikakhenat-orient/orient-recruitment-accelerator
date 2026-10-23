"""Unit tests for the authorisation policy (permission + object-level authz)."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import PermissionDeniedError
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import (
    can_access_campaign,
    has_permission,
    require_campaign_permission,
    require_permission,
)
from app.modules.identity.schemas import AuthenticatedActor


def _actor(permissions: set[str], campaigns: set[uuid.UUID]) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=uuid.uuid4(),
        organisation_id=uuid.uuid4(),
        email="synthetic@example.com",
        role_names=["recruiter"],
        permissions=permissions,
        assigned_campaign_ids=campaigns,
    )


def test_has_and_require_permission() -> None:
    actor = _actor({Permission.CAMPAIGN_CREATE.value}, set())
    assert has_permission(actor, Permission.CAMPAIGN_CREATE)
    require_permission(actor, Permission.CAMPAIGN_CREATE)
    with pytest.raises(PermissionDeniedError):
        require_permission(actor, Permission.THRESHOLD_CHANGE)


def test_object_level_authz_blocks_unassigned_campaign() -> None:
    assigned = uuid.uuid4()
    other = uuid.uuid4()
    actor = _actor({Permission.APPLICATION_REVIEW.value}, {assigned})
    assert can_access_campaign(actor, assigned) is True
    assert can_access_campaign(actor, other) is False
    # Holds the permission but is NOT assigned to the campaign -> denied (Req 1.2.4).
    with pytest.raises(PermissionDeniedError):
        require_campaign_permission(actor, Permission.APPLICATION_REVIEW, other)
    # Assigned + holds permission -> allowed.
    require_campaign_permission(actor, Permission.APPLICATION_REVIEW, assigned)


def test_permission_without_assignment_is_insufficient() -> None:
    campaign = uuid.uuid4()
    actor = _actor({Permission.SCREENING_EXECUTE.value}, set())
    with pytest.raises(PermissionDeniedError):
        require_campaign_permission(actor, Permission.SCREENING_EXECUTE, campaign)
