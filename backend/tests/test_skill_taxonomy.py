"""Tests for the skill taxonomy (Req 6.1): related aliases are not exact equivalents."""

from __future__ import annotations

import uuid

from app.modules.skills import service
from app.modules.skills.models import AliasRelationship
from tests.factories import make_org


def test_canonical_name_resolves(db_session) -> None:
    org = make_org(db_session)
    skill = service.create_skill(db_session, organisation_id=org.id,
                                 canonical_name="Kubernetes", category="platform",
                                 actor_id=uuid.uuid4())
    assert service.resolve_skill(db_session, org.id, "kubernetes").id == skill.id


def test_abbreviation_alias_resolves(db_session) -> None:
    org = make_org(db_session)
    skill = service.create_skill(db_session, organisation_id=org.id,
                                 canonical_name="Kubernetes", category=None,
                                 actor_id=uuid.uuid4())
    service.add_alias(db_session, organisation_id=org.id, skill_id=skill.id, alias="k8s",
                      relationship_type=AliasRelationship.ABBREVIATION, actor_id=uuid.uuid4())
    assert service.resolve_skill(db_session, org.id, "k8s").id == skill.id


def test_related_alias_does_not_resolve(db_session) -> None:
    org = make_org(db_session)
    skill = service.create_skill(db_session, organisation_id=org.id,
                                 canonical_name="Kubernetes", category=None,
                                 actor_id=uuid.uuid4())
    # Docker is RELATED to Kubernetes but is NOT an equivalent; it must not resolve.
    service.add_alias(db_session, organisation_id=org.id, skill_id=skill.id, alias="docker",
                      relationship_type=AliasRelationship.RELATED, actor_id=uuid.uuid4())
    assert service.resolve_skill(db_session, org.id, "docker") is None


def test_unknown_token_returns_none(db_session) -> None:
    org = make_org(db_session)
    assert service.resolve_skill(db_session, org.id, "nonexistent-skill") is None
