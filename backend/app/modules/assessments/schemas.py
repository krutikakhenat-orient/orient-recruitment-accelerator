"""Assessment Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.assessments.models import AssessmentRecommendation


class AssessmentSubmit(BaseModel):
    application_id: uuid.UUID
    criteria_scores: dict[str, Any] = Field(default_factory=dict)
    recommendation: AssessmentRecommendation
    problem_solving_notes: str | None = None
    role_understanding_notes: str | None = None
    interview_notes: str | None = None
    conflict_declared: bool = False
    conflict_detail: str | None = None


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    panel_member_id: uuid.UUID
    recommendation: str
    conflict_declared: bool


class AssessmentDetailRead(BaseModel):
    """Full saved assessment, used to rehydrate the Assessment tab so entered values
    survive a tab switch or page refresh, and for Recruiter Admin to review the verdict."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    panel_member_id: uuid.UUID
    criteria_scores: dict[str, Any]
    problem_solving_notes: str | None
    role_understanding_notes: str | None
    interview_notes: str | None
    recommendation: str
    conflict_declared: bool
    conflict_detail: str | None


class AssessableApplicationRead(BaseModel):
    """Minimal view for a panel member: who to assess, no screening internals."""

    application_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_name: str


class PanelInterviewRead(BaseModel):
    """One interview on a panel member's worklist. ``stage`` tells the UI what to do next:
    'to_check_in' (candidate scheduled, confirm arrival), 'to_assess' (checked in, submit
    assessment), 'to_check_out' (assessed, finish the interview) or 'completed' (checked
    out). ``has_assessment`` is True once this panel member has saved an assessment."""

    application_id: uuid.UUID
    campaign_id: uuid.UUID
    invitation_id: uuid.UUID | None
    candidate_name: str
    state: str
    stage: str  # to_check_in | to_assess | to_check_out | completed
    has_assessment: bool = False


class PanelDashboardRead(BaseModel):
    """Counts for the Interview Panel dashboard."""

    to_check_in: int
    to_assess: int
    to_check_out: int
    completed: int
    total: int
    interviews: list[PanelInterviewRead]
