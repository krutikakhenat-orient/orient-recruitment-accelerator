"""Identity & Access Pydantic schemas (never serialize ORM directly)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, min_length=6, max_length=8)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    role_names: list[str] = Field(default_factory=list)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    email: EmailStr
    display_name: str
    is_active: bool
    mfa_enabled: bool


class AuthenticatedActor(BaseModel):
    """The resolved identity + effective permissions for the current request."""

    user_id: uuid.UUID
    organisation_id: uuid.UUID
    email: str
    role_names: list[str]
    permissions: set[str]
    assigned_campaign_ids: set[uuid.UUID]
