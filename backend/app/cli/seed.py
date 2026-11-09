"""Seed SYNTHETIC foundation data for local development.

Creates one organisation, the default roles with their permission bundles, and one
synthetic user per staff role. ALL data created here is synthetic and clearly marked;
no real people. Never run against production data.

Usage:
    python -m app.cli.seed
"""

from __future__ import annotations

import os
import sys
import uuid

from sqlalchemy.orm import Session

from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.models import Role, User, UserRole
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName
from app.modules.induction.service import seed_developer_video
from app.modules.organisations.repository import get_or_create_organisation
from app.modules.policies.models import PolicyDocument, PolicyStatus

# Synthetic local-dev password. Clearly non-production; replace in any real environment.
SYNTHETIC_DEV_PASSWORD = "SyntheticDevPassword123"  # noqa: S105

ORG_NAME = "SYNTHETIC Orient Demo Org"


def _seed_password() -> str:
    """Password for seeded synthetic users: ORA_SEED_PASSWORD if set, else the dev default.

    Shared/hosted trial environments set ORA_SEED_PASSWORD so the well-known dev password is
    not what testers log in with. Read from the environment only (never hard-coded)."""
    return os.environ.get("ORA_SEED_PASSWORD") or SYNTHETIC_DEV_PASSWORD


def seed(db: Session) -> None:
    org = get_or_create_organisation(db, ORG_NAME)
    password = _seed_password()

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
            password_hash=hash_password(password),
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

    # Developer-provisioned induction video so local dev has a playable video. Idempotent:
    # repeated seeds reuse the existing video row + object-store blob (no duplicates).
    seed_developer_video(db, org.id)

    _seed_sample_policies(db, org.id)

    db.commit()


# Synthetic sample policies so the HR assistant and the policy library can be tried locally.
# They are clearly marked as samples and are NOT real company policy.
_SAMPLE_POLICIES: tuple[tuple[str, str, str | None, str], ...] = (
    (
        "Leave policy (sample)", "policy", None,
        "SYNTHETIC SAMPLE. Employees receive 20 days of paid annual leave each year. "
        "Unused leave can be carried forward up to 5 days. Leave requests should be made at "
        "least 3 working days ahead and approved by the reporting manager.",
    ),
    (
        "Working hours and attendance (sample)", "policy", None,
        "SYNTHETIC SAMPLE. Standard working hours are 9:30 to 18:00, Monday to Friday. "
        "Employees mark attendance daily. Working from home needs prior approval from the "
        "reporting manager.",
    ),
    (
        "Code of conduct (sample)", "policy", None,
        "SYNTHETIC SAMPLE. Treat colleagues and candidates with respect. Keep company and "
        "personal information confidential. Report any concern to HR without fear of "
        "retaliation.",
    ),
    (
        "First week checklist (sample)", "sop", "Engineering",
        "SYNTHETIC SAMPLE. On day one collect your laptop and access card. Meet your "
        "reporting manager and complete the induction video. By the end of the first week "
        "set up your development environment and read the team handbook.",
    ),
)


def _seed_sample_policies(db: Session, organisation_id: uuid.UUID) -> None:
    for title, kind, department, body in _SAMPLE_POLICIES:
        exists = (
            db.query(PolicyDocument)
            .filter(PolicyDocument.organisation_id == organisation_id,
                    PolicyDocument.title == title)
            .first()
        )
        if exists is not None:
            continue
        db.add(
            PolicyDocument(
                organisation_id=organisation_id, family_id=uuid.uuid4(), title=title,
                kind=kind, department=department, body=body, version=1,
                status=PolicyStatus.APPROVED.value,
            )
        )
    db.flush()


def main() -> int:
    settings = get_settings()
    if settings.environment == Environment.PRODUCTION:
        print("Refusing to seed synthetic data in a production environment.", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        seed(db)
        print(f"Seeded synthetic data into organisation '{ORG_NAME}'.")
        if os.environ.get("ORA_SEED_PASSWORD"):
            print("Synthetic staff logins use the password from ORA_SEED_PASSWORD.")
        else:
            print("Synthetic staff logins use password:", SYNTHETIC_DEV_PASSWORD)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
