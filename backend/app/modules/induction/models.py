"""Induction ORM models.

Models here are never serialized directly; services map them to Pydantic schemas.
Org-scoped: every row carries ``organisation_id`` so tenant isolation holds (ADR-0016).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class InductionVideo(UUIDPrimaryKey, Timestamped, Base):
    """The developer-provisioned induction video for an organisation.

    There is no frontend path to create this row; a developer seeds it (see
    ``app.modules.induction.service.seed_developer_video``). The actual bytes live in the
    object store under ``storage_key``; this row only holds metadata.
    """

    __tablename__ = "induction_video"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InductionCompletion(UUIDPrimaryKey, Timestamped, Base):
    """Records that a user completed the induction video. One row per user+video."""

    __tablename__ = "induction_completion"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "induction_video_id", name="uq_induction_completion_user_video"
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    induction_video_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("induction_video.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
