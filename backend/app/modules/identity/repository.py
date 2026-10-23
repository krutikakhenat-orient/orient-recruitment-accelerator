"""Identity & Access data access. All queries are organisation-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.identity.models import (
    CampaignAssignment,
    Organisation,
    Role,
    User,
    UserRole,
)


def get_user_by_email(db: Session, organisation_id: uuid.UUID, email: str) -> User | None:
    stmt = select(User).where(
        User.organisation_id == organisation_id,
        User.email == email.lower(),
    )
    return db.execute(stmt).scalars().first()


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_roles_by_names(
    db: Session, organisation_id: uuid.UUID, names: list[str]
) -> list[Role]:
    if not names:
        return []
    stmt = select(Role).where(
        Role.organisation_id == organisation_id,
        Role.name.in_(names),
    )
    return list(db.execute(stmt).scalars())


def effective_permissions(db: Session, user: User) -> set[str]:
    permissions: set[str] = set()
    for user_role in user.roles:
        permissions.update(user_role.role.permissions)
    return permissions


def assigned_campaign_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    stmt = select(CampaignAssignment.campaign_id).where(
        CampaignAssignment.user_id == user_id
    )
    return set(db.execute(stmt).scalars())


def create_user(db: Session, user: User, roles: list[Role]) -> User:
    db.add(user)
    db.flush()
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    return user


def get_organisation(db: Session, organisation_id: uuid.UUID) -> Organisation | None:
    return db.get(Organisation, organisation_id)


def list_users(db: Session, organisation_id: uuid.UUID) -> list[User]:
    stmt = (
        select(User)
        .where(User.organisation_id == organisation_id, User.is_active.is_(True))
        .order_by(User.display_name)
    )
    return list(db.execute(stmt).scalars())
