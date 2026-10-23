"""Test the synthetic seed routine creates roles and staff users correctly."""

from __future__ import annotations

from app.cli.seed import ORG_NAME, seed
from app.modules.identity.models import Role, User
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName


def test_seed_creates_roles_and_staff_users(db_session) -> None:
    seed(db_session)

    roles = db_session.query(Role).all()
    assert len(roles) == len(DEFAULT_ROLE_PERMISSIONS)

    users = db_session.query(User).all()
    staff_count = len([r for r in RoleName if r is not RoleName.CANDIDATE])
    assert len(users) == staff_count
    # All seeded identities are clearly marked synthetic.
    assert all(u.display_name.startswith("SYNTHETIC") for u in users)
    assert all(u.email.endswith("@example.com") for u in users)


def test_seed_is_idempotent(db_session) -> None:
    seed(db_session)
    first_users = db_session.query(User).count()
    seed(db_session)
    assert db_session.query(User).count() == first_users
    assert ORG_NAME.startswith("SYNTHETIC")
