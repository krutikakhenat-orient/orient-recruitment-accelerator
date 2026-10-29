"""Induction Pydantic schemas (never serialize ORM directly)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InductionVideoRead(BaseModel):
    """Public metadata for the induction video (never exposes the storage key)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    content_type: str


class InductionStatusRead(BaseModel):
    """Whether a video exists for the org and whether the current user finished it."""

    has_video: bool
    completed: bool
    completed_at: datetime | None


class CompletionResult(BaseModel):
    """Result of recording (or re-confirming) an induction completion."""

    completed: bool
    completed_at: datetime
