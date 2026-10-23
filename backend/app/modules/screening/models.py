"""Screening ORM models (Req 8.1-8.3).

A ScreeningRun is an IMMUTABLE record of one deterministic evaluation of an application.
It stores every version pointer (JD, rule-set, threshold, form, extraction), the input
hash, and the engine version so the run is fully reproducible. Re-evaluation creates a NEW
run; existing runs are never modified (Req 11.2). CriterionResults give the explainable,
per-criterion breakdown (evidence, awarded/max, reason).
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base, UUIDPrimaryKey


class ScreeningRecommendation(str, Enum):
    READY_FOR_HR_REVIEW = "ready_for_hr_review"
    MANDATORY_CONFIRMED = "mandatory_criterion_confirmed"
    MANDATORY_NOT_CONFIRMED = "mandatory_criterion_not_confirmed"
    ADDITIONAL_INFO_REQUIRED = "additional_information_required"
    DATA_CONFLICT = "data_conflict"
    LOW_EXTRACTION_CONFIDENCE = "low_extraction_confidence"
    RECOMMENDED_FOR_INTERVIEW_REVIEW = "recommended_for_interview_review"
    BORDERLINE_REVIEW = "borderline_review"
    WAITLIST_REVIEW = "waitlist_review"


class EligibilityOutcome(str, Enum):
    ELIGIBLE = "eligible"
    NOT_CONFIRMED = "not_confirmed"
    NEEDS_REVIEW = "needs_review"


class ScreeningRun(UUIDPrimaryKey, Base):
    __tablename__ = "screening_run"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Version pointers used for this run (reproducibility, Req 8.1.3).
    jd_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    rule_set_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    threshold_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    form_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    eligibility_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    recommendation: Mapped[str] = mapped_column(String(48), nullable=False)
    manual_review_required: Mapped[bool] = mapped_column(nullable=False, default=False)

    # True when a candidate self-claim exceeds verified resume evidence or rests on
    # low-confidence extraction. A conflict ALWAYS routes to human review and NEVER
    # auto-rejects (responsible-ai.md). Recorded here so the UI can show a warning banner.
    conflict_flagged: Mapped[bool] = mapped_column(nullable=False, default=False)
    conflict_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    processing_errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)

    results: Mapped[list[CriterionResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class CriterionResult(UUIDPrimaryKey, Base):
    __tablename__ = "criterion_result"

    screening_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screening_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_name: Mapped[str] = mapped_column(String(255), nullable=False)
    criterion_type: Mapped[str] = mapped_column(String(48), nullable=False)
    mandatory: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Optional skill-checklist tier (must_have / good_to_have / nice_to_have) for grouped
    # display. Passthrough from the rule; never affects the deterministic score.
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    awarded_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped[ScreeningRun] = relationship(back_populates="results")
