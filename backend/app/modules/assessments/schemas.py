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


class AssessableApplicationRead(BaseModel):
    """Minimal view for a panel member: who to assess, no screening internals."""

    application_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_name: str


class PanelInterviewRead(BaseModel):
    """One interview on a panel member's worklist. ``stage`` tells the UI what to do next:
    'to_attend' (confirm attendance), 'to_assess' (submit assessment) or 'completed'."""

    application_id: uuid.UUID
    campaign_id: uuid.UUID
    invitation_id: uuid.UUID | None
    candidate_name: str
    state: str
    stage: str  # to_attend | to_assess | completed


class PanelDashboardRead(BaseModel):
    """Counts for the Interview Panel dashboard."""

    to_attend: int
    to_assess: int
    completed: int
    total: int
    interviews: list[PanelInterviewRead]
