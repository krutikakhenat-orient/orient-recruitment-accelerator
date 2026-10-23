"""Integration tests for authentication: lockout, MFA, token refresh, audit."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import generate_totp_secret
from app.modules.audit.service import verify_chain
from app.modules.identity import service
from app.modules.identity.permissions import RoleName
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[arg-type]
        jwt_secret="service-test-secret-at-least-32-characters!!",
        max_failed_logins=3,
        lockout_seconds=900,
    )


def test_successful_login_issues_tokens_and_audits(db_session, settings) -> None:
    org = make_org(db_session)
    role = make_role(db_session, org, RoleName.RECRUITER_ADMIN)
    user = make_user(db_session, org, roles=[role], password=PASSWORD)

    tokens = service.authenticate(
        db_session, settings, org.id, user.email, PASSWORD, totp_code=None
    )
    assert tokens.access_token and tokens.refresh_token

    actor = service.resolve_actor(db_session, settings, tokens.access_token)
    assert actor.email == user.email
    assert "campaign.create" in actor.permissions
    assert verify_chain(db_session, org.id) is True


def test_wrong_password_increments_and_locks(db_session, settings) -> None:
    org = make_org(db_session)
    user = make_user(db_session, org, password=PASSWORD)

    for _ in range(settings.max_failed_logins):
        with pytest.raises(AuthenticationError):
            service.authenticate(db_session, settings, org.id, user.email, "nope", None)

    db_session.refresh(user)
    assert user.failed_login_count >= settings.max_failed_logins
    assert user.locked_until is not None

    # Even correct password is blocked while locked.
    with pytest.raises(AuthenticationError, match="locked"):
        service.authenticate(db_session, settings, org.id, user.email, PASSWORD, None)


def test_unknown_user_returns_generic_error_no_enumeration(db_session, settings) -> None:
    org = make_org(db_session)
    with pytest.raises(AuthenticationError, match="Invalid credentials"):
        service.authenticate(
            db_session, settings, org.id, "ghost@example.com", "whatever", None
        )


def test_mfa_required_when_enabled(db_session, settings) -> None:
    org = make_org(db_session)
    user = make_user(db_session, org, password=PASSWORD)
    user.mfa_enabled = True
    user.totp_secret = generate_totp_secret()
    db_session.flush()

    with pytest.raises(AuthenticationError, match="MFA"):
        service.authenticate(db_session, settings, org.id, user.email, PASSWORD, None)

    import pyotp

    code = pyotp.TOTP(user.totp_secret).now()
    tokens = service.authenticate(db_session, settings, org.id, user.email, PASSWORD, code)
    assert tokens.access_token


def test_refresh_rotates_access_token(db_session, settings) -> None:
    org = make_org(db_session)
    user = make_user(db_session, org, password=PASSWORD)
    tokens = service.authenticate(db_session, settings, org.id, user.email, PASSWORD, None)
    refreshed = service.refresh(db_session, settings, tokens.refresh_token)
    assert refreshed.access_token

    # An access token must not be accepted by refresh.
    with pytest.raises(AuthenticationError):
        service.refresh(db_session, settings, tokens.access_token)


def test_lockout_expiry_allows_login(db_session, settings) -> None:
    org = make_org(db_session)
    user = make_user(db_session, org, password=PASSWORD)
    user.locked_until = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=1)
    user.failed_login_count = 99
    db_session.flush()
    # Past lockout should not block.
    tokens = service.authenticate(db_session, settings, org.id, user.email, PASSWORD, None)
    assert tokens.access_token
