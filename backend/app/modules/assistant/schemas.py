"""HR assistant request/response schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=300)


class AnswerSource(BaseModel):
    ref: int = 1  # the [n] marker used in the answer text
    policy_id: uuid.UUID
    title: str
    version: int
    page: int | None = None
    excerpt: str = ""


class AskResponse(BaseModel):
    answered: bool
    answer: str
    sources: list[AnswerSource]
    route_to_hr: bool
    note: str
    # not_found | self_service | guardrail | answered
    outcome: str
    # Backend that produced the reply ("bedrock_kb" or "keyword"); null when no search ran.
    answered_via: str | None
    # True when smart search is switched on but this reply came from the keyword fallback.
    smart_search_unavailable: bool = False
    query_id: uuid.UUID


class UnansweredRead(BaseModel):
    id: uuid.UUID
    question: str
    asked_at: dt.datetime


class FeedbackRequest(BaseModel):
    query_id: uuid.UUID
    helpful: bool
    comment: str | None = Field(default=None, max_length=300)


class FeedbackRead(BaseModel):
    id: uuid.UUID
    query_id: uuid.UUID
    helpful: bool


class EscalateRequest(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    contact_preference: str = Field(default="in_app", pattern="^(in_app|email)$")


class QuestionCount(BaseModel):
    question: str
    count: int


class ReviewDueRead(BaseModel):
    policy_id: uuid.UUID
    title: str
    version: int
    review_due_date: dt.date


class InsightsRead(BaseModel):
    """Aggregates only; nothing here identifies who asked (Req 8.3)."""

    period_days: int
    total_questions: int
    answered: int
    not_found: int
    self_service: int
    guardrail_blocked: int
    by_backend: dict[str, int]
    helpful: int
    not_helpful: int
    not_helpful_rate: float | None
    top_questions: list[QuestionCount]
    top_unanswered: list[QuestionCount]
    open_hr_questions: int
    review_due: list[ReviewDueRead]
