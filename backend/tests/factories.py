"""Synthetic test-data helpers. All data here is synthetic, never real people."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.identity.models import Organisation, Role, User, UserRole
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName


def make_org(db: Session, name: str = "SYNTHETIC Org") -> Organisation:
    org = Organisation(name=name, is_active=True)
    db.add(org)
    db.flush()
    return org


def make_role(db: Session, org: Organisation, role_name: RoleName) -> Role:
    perms = sorted(p.value for p in DEFAULT_ROLE_PERMISSIONS[role_name])
    role = Role(
        organisation_id=org.id,
        name=role_name.value,
        description=f"SYNTHETIC {role_name.value}",
        permissions=perms,
    )
    db.add(role)
    db.flush()
    return role


def make_user(
    db: Session,
    org: Organisation,
    *,
    email: str = "synthetic.user@example.com",
    password: str = "CorrectHorseBatteryStaple1",
    roles: list[Role] | None = None,
) -> User:
    user = User(
        organisation_id=org.id,
        email=email.lower(),
        display_name="SYNTHETIC User",
        password_hash=hash_password(password),
    )
    db.add(user)
    db.flush()
    for role in roles or []:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    db.refresh(user)
    return user


def random_campaign_id() -> uuid.UUID:
    return uuid.uuid4()
