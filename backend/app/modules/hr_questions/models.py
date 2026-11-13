"""HR question inbox (migration 0014).

Unlike the anonymous query log, an HR question records who asked: the employee chose to send
it to HR so HR can reply. Only HR Policy Managers and the asker can read it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class HrQuestionStatus(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"


class ContactPreference(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"


class HrQuestion(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "hr_question"
    __table_args__ = (
        UniqueConstraint("organisation_id", "asked_by", "idempotency_key",
                         name="uq_hr_question_idempotency"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asked_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_preference: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContactPreference.IN_APP.value
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=HrQuestionStatus.OPEN.value, index=True
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    answered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
