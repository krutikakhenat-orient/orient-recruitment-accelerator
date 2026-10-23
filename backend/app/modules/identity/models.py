"""Identity & Access ORM models.

Models here are never serialized directly; services map them to Pydantic schemas.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class Organisation(UUIDPrimaryKey, Timestamped, Base):
    """Organisation / tenant boundary. MVP is single-org but the key is carried
    everywhere so multi-tenant isolation can be added later (ADR-0016)."""

    __tablename__ = "organisation"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Role(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_role_org_name"),)

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Permission grants stored as a JSON array of permission strings.
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class User(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("organisation_id", "email", name="uq_user_org_email"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Auth hardening
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # MFA scaffold (readiness; not enforced in MVP)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class UserRole(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(lazy="joined")


class CampaignAssignment(UUIDPrimaryKey, Timestamped, Base):
    """Object-level authorisation link: which users may act on which campaign.

    A permission grant is only effective for a campaign the user is assigned to
    (Req 1.2.3, 1.2.4). The campaign row lives in the Campaigns module; this table
    references its id without a hard FK to keep module coupling loose at the DB level.
    """

    __tablename__ = "campaign_assignment"
    __table_args__ = (
        UniqueConstraint("user_id", "campaign_id", name="uq_campaign_assignment"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
