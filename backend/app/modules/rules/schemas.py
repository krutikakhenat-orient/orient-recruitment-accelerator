"""Rules & thresholds Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RuleSetVersionCreate(BaseModel):
    campaign_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    rules: list[dict[str, Any]] = Field(min_length=1)


class RuleSetFromJdRequest(BaseModel):
    campaign_id: uuid.UUID


class RuleSetVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_set_id: uuid.UUID
    version_number: int
    status: str
    rules: list[dict[str, Any]]


class RuleSetRejectRequest(BaseModel):
    change_reason: str = Field(min_length=1, max_length=1000)


class PendingRuleSetRead(BaseModel):
    """A draft rule-set version awaiting approval, with its campaign for the Approvals UI."""

    id: uuid.UUID
    rule_set_id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    version_number: int
    status: str
    rules: list[dict[str, Any]]


class ThresholdChangeRequest(BaseModel):
    campaign_id: uuid.UUID
    review_below: float = Field(ge=0, le=100)
    recommend_at_or_above: float = Field(ge=0, le=100)
    change_reason: str = Field(min_length=1, max_length=1000)
    # The distinct approver for four-eyes governance (must differ from the caller).
    approver_id: uuid.UUID


class ThresholdVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    threshold_set_id: uuid.UUID
    version_number: int
    status: str
    review_below: float
    recommend_at_or_above: float
    change_reason: str
