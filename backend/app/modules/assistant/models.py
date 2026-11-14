"""Assistant feedback (migration 0014). Like the query log, it stores no user identifier."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class AssistantFeedback(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "assistant_feedback"
    __table_args__ = (UniqueConstraint("query_log_id", name="uq_assistant_feedback_query"),)

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_log_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assistant_query_log.id", ondelete="CASCADE"), nullable=False, index=True
    )
    helpful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True)
