"""Hiring decision Pydantic schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.decisions.models import DecisionType


class DecisionRequest(BaseModel):
    application_id: uuid.UUID
    decision_type: DecisionType
    reason: str = Field(min_length=1, max_length=1000)


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    decision_type: str
    status: str
    reason: str


class AssessmentSummary(BaseModel):
    """A panel member's verdict, shown to the decision-maker."""

    recommendation: str
    criteria_scores: dict[str, int | float | str]
    interview_notes: str | None = None
    conflict_declared: bool = False


class PendingDecisionRead(BaseModel):
    """An assessed candidate awaiting a hiring decision, with the panel's assessments."""

    application_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_name: str
    assessments: list[AssessmentSummary]


class OutcomeRead(BaseModel):
    """A decided candidate (selected / rejected / hold) for the outcomes overview.

    Contact details are intentionally excluded; they are revealed per candidate through the
    audited candidate.view_pii endpoint.
    """

    application_id: uuid.UUID
    candidate_id: uuid.UUID
    campaign_name: str
    candidate_name: str
    outcome: str
    reason: str | None = None
