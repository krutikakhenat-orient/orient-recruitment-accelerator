"""Human-review Pydantic schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.review.models import ReviewActionType


class ReviewItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    reason: str
    detail: str | None
    status: str
    screening_run_id: uuid.UUID | None


class ReviewActionRequest(BaseModel):
    action_type: ReviewActionType
    reason: str = Field(min_length=1, max_length=1000)
    original_value: str | None = None
    corrected_value: str | None = None
    resolves_item: bool = False


class ReviewActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    review_item_id: uuid.UUID
    action_type: str
    original_value: str | None
    corrected_value: str | None
    reason: str
    resolves_item: bool
