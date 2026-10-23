"""Application Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class SubmissionResponse(BaseModel):
    application_id: uuid.UUID
    state: str
    manual_review: bool
    # Deliberately minimal: candidates never see internal scores or reviewer notes.
    message: str


class ApplicationStatusResponse(BaseModel):
    """Candidate-facing screening status for the public application screen.

    Exposes ONLY a coarse status and the candidate message — never the raw score, evidence,
    recommendation or notes. ``status`` is 'pending' | 'scored' | 'failed'.
    """

    status: str
    message: str


class ResumePreviewResponse(BaseModel):
    """Suggested form answers parsed from an uploaded resume (pre-fill only).

    ``extracted`` is False when the resume text could not be read. ``fields`` maps form field
    keys to suggested string values the candidate can edit. Nothing is stored server-side.
    """

    extracted: bool
    fields: dict[str, str]


class ExtractedFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_name: str
    extracted_value: str | None
    verified_value: str | None
    source_span: str | None
    extraction_method: str
    confidence: float
    status: str


class FieldVerifyRequest(BaseModel):
    corrected_value: str | None = None
    correction_reason: str | None = None


class WalkInIntakeResult(BaseModel):
    filename: str
    accepted: bool
    application_id: uuid.UUID | None
    duplicate: bool
    detail: str
    score: float | None = None
    manual_review: bool = False


class WalkInIntakeResponse(BaseModel):
    campaign_id: uuid.UUID
    total: int
    accepted: int
    rejected: int
    results: list[WalkInIntakeResult]


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_id: uuid.UUID
    state: str
    answers: dict[str, Any]
    version: int


class RankedApplicationRead(BaseModel):
    """An application plus its latest screening summary, for the ranked HR table.

    The latest-run fields are embedded so the applications list can be ranked server-side
    (by score, descending, unscored last) WITHOUT the UI making one screening-runs call per
    candidate. Candidates are ranked only within their own campaign. ``rank`` is 1-based over
    the scored candidates in this campaign; unscored candidates have ``rank = None`` and sort
    last. ``score`` is the 0..100 fit score of the latest run; ``scored`` is False when the
    candidate has no completed run yet (awaiting screening) or the run could not score.
    """

    id: uuid.UUID
    organisation_id: uuid.UUID
    campaign_id: uuid.UUID
    candidate_id: uuid.UUID
    state: str
    answers: dict[str, Any]
    version: int
    # Latest-run summary (None when never screened).
    rank: int | None = None
    scored: bool = False
    score: float | None = None
    recommendation: str | None = None
    manual_review_required: bool | None = None
    conflict_flagged: bool | None = None
    latest_run_id: uuid.UUID | None = None
