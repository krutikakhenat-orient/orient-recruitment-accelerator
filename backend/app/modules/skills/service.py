"""Skill taxonomy service (Req 6.1)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.modules.skills.models import (
    EQUIVALENT_RELATIONSHIPS,
    AliasRelationship,
    Skill,
    SkillAlias,
)


def create_skill(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    canonical_name: str,
    category: str | None,
    actor_id: uuid.UUID,
) -> Skill:
    existing = db.execute(
        select(Skill).where(
            Skill.organisation_id == organisation_id,
            Skill.canonical_name == canonical_name,
        )
    ).scalars().first()
    if existing is not None:
        raise ConflictError("A skill with this canonical name already exists")
    skill = Skill(
        organisation_id=organisation_id, canonical_name=canonical_name,
        category=category, created_by=actor_id,
    )
    db.add(skill)
    db.flush()
    return skill


def add_alias(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    skill_id: uuid.UUID,
    alias: str,
    relationship_type: AliasRelationship,
    actor_id: uuid.UUID,
) -> SkillAlias:
    skill = db.get(Skill, skill_id)
    if skill is None or skill.organisation_id != organisation_id:
        raise ValidationError("Skill not found")
    record = SkillAlias(
        organisation_id=organisation_id, skill_id=skill_id, alias=alias.strip().lower(),
        relationship_type=relationship_type.value, approved_by=actor_id,
    )
    db.add(record)
    db.flush()
    return record


def resolve_skill(db: Session, organisation_id: uuid.UUID, token: str) -> Skill | None:
    """Resolve a free-text token to a canonical skill.

    Matches the canonical name directly, or an alias whose relationship is EQUIVALENT
    (exact/abbreviation/previous_name). A RELATED alias never resolves (not equivalent).
    """
    needle = token.strip().lower()

    direct = db.execute(
        select(Skill).where(
            Skill.organisation_id == organisation_id,
            Skill.active.is_(True),
        )
    ).scalars()
    for skill in direct:
        if skill.canonical_name.strip().lower() == needle:
            return skill

    alias = db.execute(
        select(SkillAlias).where(
            SkillAlias.organisation_id == organisation_id,
            SkillAlias.alias == needle,
        )
    ).scalars().first()
    if alias is not None and alias.relationship_type in EQUIVALENT_RELATIONSHIPS:
        return db.get(Skill, alias.skill_id)
    return None
