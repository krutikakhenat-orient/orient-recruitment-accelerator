"""Screening Pydantic schemas (explainable score, Req 8.3)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class CriterionResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criterion_name: str
    criterion_type: str
    mandatory: bool
    tier: str | None = None
    outcome: str
    expected: str | None
    candidate_evidence: str | None
    evidence_source: str | None
    confidence: float | None
    max_score: float
    awarded_score: float
    reason: str


class RescoreSummaryRead(BaseModel):
    """Result of repairing a campaign: how many applications were re-screened against the
    freshly regenerated JD-derived criteria, and how many progressed to the interview panel."""

    rescored: int
    criteria_count: int
    progressed: int


class ScreeningRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    rule_set_version_id: uuid.UUID
    threshold_version_id: uuid.UUID | None
    score: float
    eligibility_outcome: str
    confidence_status: str
    recommendation: str
    manual_review_required: bool
    conflict_flagged: bool = False
    conflict_detail: str | None = None
    input_data_hash: str
    engine_version: str
    completed_at: dt.datetime | None
    results: list[CriterionResultRead]
