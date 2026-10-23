"""Skill taxonomy models (Req 6.1).

A controlled vocabulary of canonical skills plus aliases. Each alias declares its
relationship to the canonical skill. Crucially, a ``related`` alias is NOT an exact
equivalent and must not be scored as one (steering/responsible-ai.md); only EXACT,
ABBREVIATION, and PREVIOUS_NAME aliases resolve to the canonical skill for matching.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class AliasRelationship(str, Enum):
    EXACT = "exact"               # synonym; resolves to canonical
    ABBREVIATION = "abbreviation"  # e.g. "k8s" -> "Kubernetes"
    PREVIOUS_NAME = "previous_name"  # former product name
    RELATED = "related"           # related but NOT equivalent; never scored as exact


# Alias relationships that resolve to the canonical skill for exact matching.
EQUIVALENT_RELATIONSHIPS = frozenset(
    {AliasRelationship.EXACT.value, AliasRelationship.ABBREVIATION.value,
     AliasRelationship.PREVIOUS_NAME.value}
)


class Skill(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "skill"
    __table_args__ = (
        UniqueConstraint("organisation_id", "canonical_name", name="uq_skill_org_name"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    aliases: Mapped[list[SkillAlias]] = relationship(
        back_populates="skill", cascade="all, delete-orphan", lazy="selectin"
    )


class SkillAlias(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "skill_alias"
    __table_args__ = (
        UniqueConstraint("organisation_id", "alias", name="uq_skill_alias"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    skill: Mapped[Skill] = relationship(back_populates="aliases")
