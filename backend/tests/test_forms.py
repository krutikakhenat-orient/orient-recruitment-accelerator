"""Tests for the dynamic form schema (Req 4.1)."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ConflictError, ValidationError
from app.modules.forms import service
from app.modules.forms.models import FieldClass
from app.modules.forms.policy import assert_field_allowed
from tests.factories import make_org


def test_baseline_draft_has_core_fields_and_no_compensation(db_session) -> None:
    org = make_org(db_session)
    version = service.create_form_draft(
        db_session, organisation_id=org.id, campaign_id=uuid.uuid4(), actor_id=uuid.uuid4()
    )
    keys = {f.key for f in version.fields}
    assert {"full_name", "email", "resume", "privacy_consent", "talent_pool_consent"} <= keys
    # Compensation is off by default.
    assert "current_ctc" not in keys
    assert version.compensation_enabled is False


def test_repeating_group_fields_carry_item_schema(db_session) -> None:
    # Education / work history are repeating groups: each carries the row column schema and
    # no column is a prohibited (protected/personal) attribute.
    org = make_org(db_session)
    version = service.create_form_draft(
        db_session, organisation_id=org.id, campaign_id=uuid.uuid4(), actor_id=uuid.uuid4()
    )
    groups = {f.key: f for f in version.fields if f.field_type == "repeating_group"}
    assert {"education_history", "work_history"} <= set(groups)

    edu = groups["education_history"]
    assert edu.item_schema is not None
    col_keys = {c["key"] for c in edu.item_schema}
    assert {"qualification", "institution"} <= col_keys

    # Simple fields never carry an item schema.
    full_name = next(f for f in version.fields if f.key == "full_name")
    assert full_name.item_schema is None


def test_compensation_fields_only_when_enabled(db_session) -> None:
    org = make_org(db_session)
    version = service.create_form_draft(
        db_session, organisation_id=org.id, campaign_id=uuid.uuid4(), actor_id=uuid.uuid4(),
        compensation_enabled=True,
    )
    keys = {f.key for f in version.fields}
    assert {"current_ctc", "current_in_hand", "expected_ctc"} <= keys


def test_prohibited_fields_are_rejected() -> None:
    for prohibited in ("date_of_birth", "gender", "religion", "disability", "photo"):
        with pytest.raises(ValidationError, match="prohibited"):
            assert_field_allowed(prohibited, FieldClass.ELIGIBILITY.value,
                                 compensation_enabled=False)


def test_compensation_field_requires_enabled_flag() -> None:
    with pytest.raises(ValidationError, match="compensation"):
        assert_field_allowed("current_compensation", FieldClass.COMPENSATION.value,
                             compensation_enabled=False)


def test_approved_form_version_is_immutable(db_session) -> None:
    org = make_org(db_session)
    version = service.create_form_draft(
        db_session, organisation_id=org.id, campaign_id=uuid.uuid4(), actor_id=uuid.uuid4()
    )
    service.approve_form_version(
        db_session, organisation_id=org.id, form_version_id=version.id, actor_id=uuid.uuid4()
    )
    with pytest.raises(ConflictError, match="already approved"):
        service.approve_form_version(
            db_session, organisation_id=org.id, form_version_id=version.id,
            actor_id=uuid.uuid4(),
        )
