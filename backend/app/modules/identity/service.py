"""Identity & Access application service.

Handles authentication (with account lockout + anomaly audit), token issue/refresh,
user creation, and resolving the authenticated actor with effective permissions and
assigned campaigns. Business rules live here; the router stays thin.
"""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AuthenticationError, ConflictError, ValidationError
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
    verify_totp,
)
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity import repository as repo
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    AuthenticatedActor,
    TokenPair,
    UserCreate,
)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _as_aware_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Normalise a possibly naive timestamp to timezone-aware UTC.

    Some drivers/backends (and SQLite) return naive datetimes even for columns
    declared timezone-aware; comparing those to an aware ``now`` raises TypeError.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _issue_tokens(settings: Settings, user: User) -> TokenPair:
    claims = {"org": str(user.organisation_id)}
    return TokenPair(
        access_token=create_token(
            settings=settings, subject=str(user.id), token_type="access", extra_claims=claims
        ),
        refresh_token=create_token(
            settings=settings, subject=str(user.id), token_type="refresh", extra_claims=claims
        ),
    )


def authenticate(
    db: Session,
    settings: Settings,
    organisation_id: uuid.UUID,
    email: str,
    password: str,
    totp_code: str | None,
) -> TokenPair:
    user = repo.get_user_by_email(db, organisation_id, email)

    # Uniform failure to avoid user enumeration (Req 16.1).
    generic_failure = AuthenticationError("Invalid credentials")

    if user is None or not user.is_active:
        raise generic_failure

    locked_until = _as_aware_utc(user.locked_until)
    if locked_until and locked_until > _now():
        _audit_auth(db, user, "auth.login_blocked_locked")
        raise AuthenticationError("Account temporarily locked")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = _now() + dt.timedelta(seconds=settings.lockout_seconds)
            _audit_auth(db, user, "auth.account_locked")
        else:
            _audit_auth(db, user, "auth.login_failed")
        db.flush()
        raise generic_failure

    if user.mfa_enabled and (
        not totp_code or not user.totp_secret or not verify_totp(user.totp_secret, totp_code)
    ):
        _audit_auth(db, user, "auth.mfa_failed")
        raise AuthenticationError("MFA verification required or failed")

    # Success: reset counters, opportunistically rehash.
    user.failed_login_count = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    db.flush()
    _audit_auth(db, user, "auth.login_succeeded")
    return _issue_tokens(settings, user)


def refresh(db: Session, settings: Settings, refresh_token: str) -> TokenPair:
    try:
        claims = decode_token(settings=settings, token=refresh_token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid refresh token") from exc
    user = repo.get_user_by_id(db, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid refresh token")
    return _issue_tokens(settings, user)


def resolve_actor(db: Session, settings: Settings, access_token: str) -> AuthenticatedActor:
    try:
        claims = decode_token(settings=settings, token=access_token, expected_type="access")
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired access token") from exc
    user = repo.get_user_by_id(db, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    role_names = [ur.role.name for ur in user.roles]
    return AuthenticatedActor(
        user_id=user.id,
        organisation_id=user.organisation_id,
        email=user.email,
        role_names=role_names,
        permissions=repo.effective_permissions(db, user),
        assigned_campaign_ids=repo.assigned_campaign_ids(db, user.id),
    )


def create_user(
    db: Session,
    organisation_id: uuid.UUID,
    data: UserCreate,
    actor_id: uuid.UUID | None,
) -> User:
    if repo.get_user_by_email(db, organisation_id, data.email) is not None:
        raise ConflictError("A user with this email already exists")
    roles = repo.get_roles_by_names(db, organisation_id, data.role_names)
    if len(roles) != len(set(data.role_names)):
        raise ValidationError("One or more roles do not exist")
    user = User(
        organisation_id=organisation_id,
        email=data.email.lower(),
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        created_by=actor_id,
    )
    user = repo.create_user(db, user, roles)
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="user.created",
            entity_type="user",
            entity_id=str(user.id),
            new_state_ref="active",
        ),
    )
    return user


def _audit_auth(db: Session, user: User, action: str) -> None:
    record_event(
        db,
        AuditEventWrite(
            organisation_id=user.organisation_id,
            actor_id=user.id,
            action=action,
            entity_type="user",
            entity_id=str(user.id),
        ),
    )
