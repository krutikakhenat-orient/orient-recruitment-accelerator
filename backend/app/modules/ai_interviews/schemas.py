"""Pydantic request/response schemas for the AI interview module.

Agent output is UNTRUSTED: everything the agent returns (questions, the final record) is
validated against these strict schemas before it is stored. No schema here has a score,
rank or verdict field, by design (responsible-ai.md).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

OpaqueRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------- agent question set


class QuestionModel(_Strict):
    id: OpaqueRef
    text: Annotated[str, StringConstraints(min_length=5, max_length=400)]
    competency: Annotated[str, StringConstraints(max_length=80)] = "general"
    source: Literal["standard", "job_description", "resume"] = "job_description"
    evidence_ref: Annotated[str, StringConstraints(max_length=300)] | None = None
    follow_up_allowed: bool = True


class QuestionSetModel(_Strict):
    """Mirror of the agent's ``QuestionSet``. ``extra='forbid'`` makes contract drift fail
    loudly (a 502) instead of silently storing unknown agent-supplied fields."""

    interview_id: uuid.UUID
    candidate_ref: OpaqueRef
    version: Annotated[str, StringConstraints(max_length=80)]
    questions: list[QuestionModel] = Field(min_length=1, max_length=20)
    generated_by: Literal["llm", "deterministic_fallback"]
    model_id: str | None = None
    prompt_version: str
    approved: bool = False
    approved_by: OpaqueRef | None = None
    created_at: dt.datetime | str | None = None


# --------------------------------------------------------------- staff API


class QuestionRead(BaseModel):
    id: str
    text: str
    competency: str
    source: str
    evidence_ref: str | None = None


class AiInterviewRead(BaseModel):
    """List/detail DTO. Deliberately excludes the transcript and the link token."""

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    status: str
    role_title: str
    questions: list[QuestionRead] = Field(default_factory=list)
    generated_by: str | None = None
    approved_at: dt.datetime | None = None
    link_expires_at: dt.datetime | None = None
    consent_given_at: dt.datetime | None = None
    start_count: int = 0
    completed_at: dt.datetime | None = None
    end_reason: str | None = None
    has_result: bool = False
    # The advisory summary (overview + per-question coverage). Never a score or verdict.
    summary: dict[str, Any] | None = None
    created_at: dt.datetime


class QuestionEdit(_Strict):
    id: OpaqueRef
    text: Annotated[str, StringConstraints(min_length=5, max_length=400)]


class ApproveRequest(_Strict):
    """Approve the question set. ``questions`` optionally edits wording and/or removes
    questions: only ids listed are kept, in the order given."""

    questions: list[QuestionEdit] | None = Field(default=None, max_length=20)
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None


class RetryRequest(_Strict):
    """Offer the candidate another attempt after an interview ended (e.g. the call dropped or
    they stopped early). A reason is required and recorded in the audit trail."""

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ApproveResponse(BaseModel):
    session: AiInterviewRead
    # Shown ONCE. Only a SHA-256 hash is stored, so it cannot be shown again.
    link_url: str
    link_expires_at: dt.datetime


class TranscriptTurnRead(BaseModel):
    speaker: str
    text: str
    question_id: str | None = None
    at: str | None = None
    flags: list[str] = Field(default_factory=list)


class TranscriptRead(BaseModel):
    session_id: uuid.UUID
    turns: list[TranscriptTurnRead]


# --------------------------------------------------------------- candidate (public) API


class PublicTokenRequest(_Strict):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]


class PublicPreviewResponse(BaseModel):
    role_title: str
    status: str
    notice_version: str
    notice_text: str
    max_minutes: int
    text_input_allowed: bool = True
    # Video evidence: offered only when enabled. Declining never blocks the interview.
    video_recording_offered: bool = False
    video_notice_version: str | None = None
    video_notice_text: str | None = None


class PublicStartRequest(_Strict):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    consent: bool
    notice_version: Annotated[str, StringConstraints(max_length=40)]
    # Separate, explicit consent to video evidence (default: no video).
    video_consent: bool = False
    video_notice_version: Annotated[str, StringConstraints(max_length=40)] | None = None


class PublicStartResponse(BaseModel):
    interview_id: uuid.UUID
    ws_url: str
    join_token: str
    # Present only when the candidate agreed to video evidence. Authorises uploading this
    # attempt's recording, nothing else; it expires and stops working when the upload ends.
    recording_token: str | None = None
    recording_max_chunk_bytes: int | None = None


class RecordingTokenRequest(_Strict):
    recording_token: Annotated[str, StringConstraints(min_length=20, max_length=200)]


class RecordingChunkResult(BaseModel):
    received: bool = True
    chunk_count: int


class RecordingRead(BaseModel):
    """Recording metadata for staff. The video itself is only reachable via playback."""

    id: uuid.UUID
    session_id: uuid.UUID
    attempt_start: int
    status: str
    content_type: str
    bytes_total: int
    consent_given_at: dt.datetime
    finished_at: dt.datetime | None = None
    delete_after: dt.datetime
    created_at: dt.datetime


class RecordingPlaybackRead(BaseModel):
    # A short-lived signed link when the storage supports it (S3). Otherwise None, and the
    # client plays from the authenticated stream endpoint instead.
    url: str | None = None
    content_type: str
    expires_in_seconds: int | None = None


# --------------------------------------------------------------- agent -> HR webhook


class AgentSummaryModel(BaseModel):
    """The parts of the agent's ``InterviewSummary`` the platform relies on. Other fields are
    kept (``extra='allow'``) so the whole advisory summary is shown to reviewers."""

    model_config = ConfigDict(extra="allow")

    interview_id: uuid.UUID
    end_reason: Annotated[str, StringConstraints(max_length=40)]
    overview: Annotated[str, StringConstraints(max_length=8000)]
    duration_seconds: int = Field(ge=0, le=86400)


class AgentTurnModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    speaker: Literal["agent", "candidate"]
    text: Annotated[str, StringConstraints(max_length=6000)]


class AgentRecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    summary: AgentSummaryModel
    transcript: list[AgentTurnModel] = Field(max_length=600)
