"""Tests for rule/threshold versioning, SoD and four-eyes (Req 7.2; AC-03, AC-12)."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ConflictError, SeparationOfDutiesError, ValidationError
from app.modules.rules import service
from tests.factories import make_org

CAMPAIGN = uuid.uuid4()
RULES = [{
    "rule_id": "R1", "name": "exp", "criterion_type": "numeric_comparison", "field": "exp",
    "operator": "gte", "expected_value": 3, "weight": 10, "mandatory": True,
}]


def test_malformed_rules_rejected_before_persist(db_session) -> None:
    org = make_org(db_session)
    with pytest.raises(ValidationError):
        service.create_rule_set_version(
            db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="rs",
            rules=[{"criterion_type": "bogus"}], actor_id=uuid.uuid4(),
        )


def test_approved_rule_set_is_immutable(db_session) -> None:
    org = make_org(db_session)
    creator = uuid.uuid4()
    approver = uuid.uuid4()
    version = service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="rs",
        rules=RULES, actor_id=creator,
    )
    approved = service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=version.id, approver_id=approver,
    )
    assert approved.is_approved
    # Re-approving an immutable version is refused.
    with pytest.raises(ConflictError, match="immutable"):
        service.approve_rule_set_version(
            db_session, organisation_id=org.id, version_id=version.id, approver_id=approver,
        )


def test_creator_cannot_be_sole_approver(db_session) -> None:
    org = make_org(db_session)
    creator = uuid.uuid4()
    version = service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="rs",
        rules=RULES, actor_id=creator,
    )
    with pytest.raises(SeparationOfDutiesError, match="sole approver"):
        service.approve_rule_set_version(
            db_session, organisation_id=org.id, version_id=version.id, approver_id=creator,
        )


def test_threshold_change_creates_new_version_with_reason(db_session) -> None:
    org = make_org(db_session)
    v = service.change_threshold(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN,
        review_below=40, recommend_at_or_above=75, change_reason="initial thresholds",
        actor_id=uuid.uuid4(), approver_id=uuid.uuid4(),
    )
    assert v.version_number == 1
    assert v.is_approved
    # A second change creates version 2 (originals preserved).
    v2 = service.change_threshold(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN,
        review_below=45, recommend_at_or_above=80, change_reason="raised bar",
        actor_id=uuid.uuid4(), approver_id=uuid.uuid4(),
    )
    assert v2.version_number == 2


def test_threshold_change_requires_reason(db_session) -> None:
    org = make_org(db_session)
    with pytest.raises(ValidationError, match="reason is required"):
        service.change_threshold(
            db_session, organisation_id=org.id, campaign_id=CAMPAIGN,
            review_below=40, recommend_at_or_above=75, change_reason="  ",
            actor_id=uuid.uuid4(), approver_id=uuid.uuid4(),
        )


def test_four_eyes_blocks_same_initiator_and_approver(db_session) -> None:
    org = make_org(db_session)
    same = uuid.uuid4()
    with pytest.raises(SeparationOfDutiesError, match="Four-eyes"):
        service.change_threshold(
            db_session, organisation_id=org.id, campaign_id=CAMPAIGN,
            review_below=40, recommend_at_or_above=75, change_reason="x",
            actor_id=same, approver_id=same,
        )
