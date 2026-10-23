"""Seed SYNTHETIC foundation data for local development.

Creates one organisation, the default roles with their permission bundles, and one
synthetic user per staff role. ALL data created here is synthetic and clearly marked;
no real people. Never run against production data.

Usage:
    python -m app.cli.seed
"""

from __future__ import annotations

import sys

from sqlalchemy.orm import Session

from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.models import Role, User, UserRole
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName
from app.modules.organisations.repository import get_or_create_organisation

# Synthetic local-dev password. Clearly non-production; replace in any real environment.
SYNTHETIC_DEV_PASSWORD = "SyntheticDevPassword123"  # noqa: S105

ORG_NAME = "SYNTHETIC Orient Demo Org"


def seed(db: Session) -> None:
    org = get_or_create_organisation(db, ORG_NAME)

    role_by_name: dict[RoleName, Role] = {}
    for role_name, perms in DEFAULT_ROLE_PERMISSIONS.items():
        existing = (
            db.query(Role)
            .filter(Role.organisation_id == org.id, Role.name == role_name.value)
            .one_or_none()
        )
        if existing is None:
            existing = Role(
                organisation_id=org.id,
                name=role_name.value,
                description=f"SYNTHETIC default role: {role_name.value}",
                permissions=sorted(p.value for p in perms),
            )
            db.add(existing)
            db.flush()
        role_by_name[role_name] = existing

    # One synthetic staff user per role (candidates self-register, so skip here).
    staff_roles = [r for r in RoleName if r is not RoleName.CANDIDATE]
    for role_name in staff_roles:
        email = f"synthetic.{role_name.value}@example.com"
        existing_user = (
            db.query(User)
            .filter(User.organisation_id == org.id, User.email == email)
            .one_or_none()
        )
        if existing_user is not None:
            continue
        user = User(
            organisation_id=org.id,
            email=email,
            display_name=f"SYNTHETIC {role_name.value.replace('_', ' ').title()}",
            password_hash=hash_password(SYNTHETIC_DEV_PASSWORD),
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role_by_name[role_name].id))
        db.flush()
        record_event(
            db,
            AuditEventWrite(
                organisation_id=org.id,
                action="seed.user_created",
                entity_type="user",
                entity_id=str(user.id),
                reason="synthetic seed data",
            ),
        )

    db.commit()


def main() -> int:
    settings = get_settings()
    if settings.environment == Environment.PRODUCTION:
        print("Refusing to seed synthetic data in a production environment.", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        seed(db)
        print(f"Seeded synthetic data into organisation '{ORG_NAME}'.")
        print("Synthetic staff logins use password:", SYNTHETIC_DEV_PASSWORD)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
