"""Request/response and domain schemas. There is intentionally no score, rank or verdict field."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

OpaqueRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]

ADVISORY_NOTICE = (
    "Advisory summary generated from the interview transcript. It is not a hiring "
    "decision, score or ranking. A human reviewer must read the transcript and decide."
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- inputs


class JobDescriptionPayload(_Strict):
    jd_id: OpaqueRef
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=20000)]
    must_have_skills: list[Annotated[str, StringConstraints(max_length=80)]] = Field(
        default_factory=list, max_length=30
    )


class ResumePayload(_Strict):
    candidate_ref: OpaqueRef  # opaque id from the HR platform, never a name or email
    text: Annotated[str, StringConstraints(min_length=1, max_length=30000)]


class PlanQuestionsRequest(_Strict):
    action: Literal["plan_questions"] = "plan_questions"
    interview_id: UUID
    job_descriptions: list[JobDescriptionPayload] = Field(min_length=1, max_length=10)
    resume: ResumePayload
    max_questions: int | None = Field(default=None, ge=1, le=15)


# ---------------------------------------------------------------- questions


class QuestionSource(StrEnum):
    STANDARD = "standard"
    JOB_DESCRIPTION = "job_description"
    RESUME = "resume"


class Question(_Strict):
    id: OpaqueRef
    text: Annotated[str, StringConstraints(min_length=5, max_length=400)]
    competency: Annotated[str, StringConstraints(max_length=80)] = "general"
    source: QuestionSource = QuestionSource.JOB_DESCRIPTION
    # Where in the JD/resume the question came from, so HR can check it.
    evidence_ref: Annotated[str, StringConstraints(max_length=300)] | None = None
    follow_up_allowed: bool = True


class QuestionSet(_Strict):
    interview_id: UUID
    candidate_ref: OpaqueRef
    version: str  # content hash: same inputs + prompt version => same version id
    questions: list[Question] = Field(min_length=1, max_length=20)
    generated_by: Literal["llm", "deterministic_fallback"]
    model_id: str | None = None
    prompt_version: str
    approved: bool = False  # set True only after a human approves, via the HR platform
    approved_by: OpaqueRef | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PrepareSessionRequest(_Strict):
    action: Literal["prepare_session"] = "prepare_session"
    interview_id: UUID
    question_set: QuestionSet
    role_title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    consent_notice_version: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    consent_given: bool


# ---------------------------------------------------------------- live interview


class Speaker(StrEnum):
    AGENT = "agent"
    CANDIDATE = "candidate"


class TranscriptTurn(_Strict):
    speaker: Speaker
    text: str
    question_id: str | None = None
    at: datetime = Field(default_factory=utc_now)
    flags: list[str] = Field(default_factory=list)  # e.g. possible_prompt_injection


class EndReason(StrEnum):
    COMPLETED = "completed"
    TIME_LIMIT = "time_limit"
    CANDIDATE_REQUESTED_STOP = "candidate_requested_stop"
    CANDIDATE_DISCONNECTED = "candidate_disconnected"
    NO_RESPONSE = "no_response"
    ERROR = "error"


# ---------------------------------------------------------------- outputs


class Coverage(StrEnum):
    ANSWERED = "answered"
    PARTIALLY_ANSWERED = "partially_answered"
    SKIPPED = "skipped"
    NOT_ASKED = "not_asked"


class QuestionAssessment(_Strict):
    question_id: str
    question_text: str
    coverage: Coverage
    answer_summary: str
    evidence_quotes: list[str] = Field(default_factory=list)  # verbatim from transcript
    needs_human_review: bool = False
    review_reason: str | None = None


class InterviewSummary(_Strict):
    interview_id: UUID
    candidate_ref: OpaqueRef
    question_set_version: str
    generated_by: Literal["llm", "deterministic_fallback"]
    model_id: str | None
    prompt_version: str
    generated_at: datetime = Field(default_factory=utc_now)
    duration_seconds: int
    end_reason: EndReason
    overview: str
    assessments: list[QuestionAssessment]
    topics_to_probe_next: list[str] = Field(default_factory=list)
    integrity_flags: list[str] = Field(default_factory=list)
    advisory_notice: str = ADVISORY_NOTICE


class InterviewRecord(_Strict):
    """What gets persisted and sent to the HR platform."""

    schema_version: Literal["1"] = "1"
    summary: InterviewSummary
    transcript: list[TranscriptTurn]
