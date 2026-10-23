"""Interview assessment ORM models (Req 10.3).

A structured, panel-member assessment kept SEPARATE from pre-screening. It captures
role-specific scores and notes plus a conflict-of-interest declaration. There are NO
personality/emotion/voice/facial/medical inference fields (responsible-ai.md); scores are
human-entered criteria only.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class AssessmentRecommendation(str, Enum):
    PROCEED = "proceed"
    HOLD = "hold"
    DO_NOT_PROCEED = "do_not_proceed"


class Assessment(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "assessment"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    panel_member_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    # Structured, human-entered criterion scores (e.g. {"technical": 4, "communication": 3}).
    criteria_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    problem_solving_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_understanding_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(16), nullable=False)
    # Panel member must declare any conflict of interest.
    conflict_declared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
