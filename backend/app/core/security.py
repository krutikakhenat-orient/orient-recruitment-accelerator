"""Security primitives: password hashing, JWT tokens, and a TOTP MFA scaffold.

- Passwords are hashed with Argon2id (argon2-cffi defaults are Argon2id).
- Access tokens are short-lived; refresh tokens are longer-lived and carry a
  distinct ``type`` claim so an access token can never be used as a refresh token.
- TOTP helpers provide MFA readiness without forcing enrolment in the MVP.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import Settings

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def create_token(
    *,
    settings: Settings,
    subject: str,
    token_type: TokenType,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    ttl = (
        settings.access_token_ttl_seconds
        if token_type == "access"
        else settings.refresh_token_ttl_seconds
    )
    issued = _now()
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(issued.timestamp()),
        "exp": int((issued + dt.timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(*, settings: Settings, token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token. Raises ``jwt.PyJWTError`` on any problem."""
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if claims.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return claims


# --- MFA (TOTP) scaffold -------------------------------------------------------

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account_name: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    # valid_window=1 tolerates minor clock skew.
    return pyotp.TOTP(secret).verify(code, valid_window=1)
