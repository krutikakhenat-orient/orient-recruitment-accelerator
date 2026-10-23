"""Unit tests for password hashing and token primitives."""

from __future__ import annotations

import time

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    create_token,
    decode_token,
    generate_totp_secret,
    hash_password,
    verify_password,
    verify_totp,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(jwt_secret="unit-test-secret-value-at-least-32-chars!!")  # type: ignore[arg-type]


def test_password_hash_is_argon2id_and_verifies() -> None:
    h = hash_password("CorrectHorseBatteryStaple1")
    assert h.startswith("$argon2id$")
    assert verify_password("CorrectHorseBatteryStaple1", h) is True
    assert verify_password("wrong-password", h) is False


def test_access_token_roundtrip() -> None:
    s = Settings(jwt_secret="unit-test-secret-value-at-least-32-chars!!")  # type: ignore[arg-type]
    token = create_token(settings=s, subject="user-1", token_type="access")
    claims = decode_token(settings=s, token=token, expected_type="access")
    assert claims["sub"] == "user-1"
    assert claims["type"] == "access"


def test_access_token_cannot_be_used_as_refresh() -> None:
    s = Settings(jwt_secret="unit-test-secret-value-at-least-32-chars!!")  # type: ignore[arg-type]
    token = create_token(settings=s, subject="user-1", token_type="access")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(settings=s, token=token, expected_type="refresh")


def test_expired_token_rejected() -> None:
    s = Settings(  # type: ignore[arg-type]
        jwt_secret="unit-test-secret-value-at-least-32-chars!!",
        access_token_ttl_seconds=1,
    )
    token = create_token(settings=s, subject="user-1", token_type="access")
    time.sleep(2)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(settings=s, token=token, expected_type="access")


def test_totp_scaffold() -> None:
    secret = generate_totp_secret()
    import pyotp

    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True
    assert verify_totp(secret, "000000") is False
