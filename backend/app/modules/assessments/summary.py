"""Interview feedback summary (long-term Req 23).

A plain, deterministic roll-up of what the interviewers themselves entered: score statistics
per criterion, how many recommended each outcome, whether they agree, and their notes
side by side. Nothing is inferred or invented, each interviewer's original entry is untouched,
and the roll-up is advisory: it never changes a recommendation or decision.

An AI-written summary is a placeholder. When a model provider is connected later it must
summarise ONLY these entries and stay behind the same advisory label.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessments.models import Assessment

ADVISORY_NOTE = (
    "This summary only gathers what the interviewers wrote. It is advisory and does not "
    "change any recommendation or decision."
)
AI_SUMMARY_NOTE = (
    "An AI-written summary is not connected yet (placeholder). This view is built from the "
    "interviewers' own scores and notes."
)


class CriterionSummary(BaseModel):
    name: str
    average: float
    lowest: float
    highest: float
    count: int


class NoteSummary(BaseModel):
    interviewer: str
    recommendation: str
    problem_solving_notes: str | None
    role_understanding_notes: str | None
    interview_notes: str | None


class FeedbackSummaryRead(BaseModel):
    application_id: uuid.UUID
    assessments_count: int
    recommendation_counts: dict[str, int]
    agreement: str  # none | single | all_agree | mixed
    criteria: list[CriterionSummary]
    notes: list[NoteSummary]
    conflicts_declared: int
    ai_summary_state: str
    ai_summary_note: str
    advisory_note: str


def _numbers(scores: dict[str, object]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in scores.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            out[name] = float(value)
    return out


def build_summary(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> FeedbackSummaryRead:
    rows = list(
        db.execute(
            select(Assessment)
            .where(
                Assessment.organisation_id == organisation_id,
                Assessment.application_id == application_id,
            )
            .order_by(Assessment.created_at)
        ).scalars()
    )
    by_criterion: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for name, value in _numbers(row.criteria_scores or {}).items():
            by_criterion[name].append(value)
    criteria = [
        CriterionSummary(
            name=name, average=round(sum(vals) / len(vals), 2), lowest=min(vals),
            highest=max(vals), count=len(vals),
        )
        for name, vals in sorted(by_criterion.items())
    ]
    counts = Counter(r.recommendation for r in rows)
    if not rows:
        agreement = "none"
    elif len(rows) == 1:
        agreement = "single"
    else:
        agreement = "all_agree" if len(counts) == 1 else "mixed"
    notes = [
        NoteSummary(
            interviewer=f"Interviewer {i}", recommendation=r.recommendation,
            problem_solving_notes=r.problem_solving_notes,
            role_understanding_notes=r.role_understanding_notes,
            interview_notes=r.interview_notes,
        )
        for i, r in enumerate(rows, start=1)
    ]
    return FeedbackSummaryRead(
        application_id=application_id, assessments_count=len(rows),
        recommendation_counts=dict(counts), agreement=agreement, criteria=criteria,
        notes=notes, conflicts_declared=sum(1 for r in rows if r.conflict_declared),
        ai_summary_state="not_configured", ai_summary_note=AI_SUMMARY_NOTE,
        advisory_note=ADVISORY_NOTE,
    )
