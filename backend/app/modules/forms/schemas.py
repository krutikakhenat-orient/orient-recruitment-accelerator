"""Form Pydantic schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class FormDraftCreate(BaseModel):
    campaign_id: uuid.UUID
    compensation_enabled: bool = False


class FormFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    field_class: str
    field_type: str
    required: bool
    order_index: int
    options: list[str] | None
    # Row column definitions for a repeating_group field; null for simple fields.
    item_schema: list[dict[str, object]] | None = None


class FormVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    form_schema_id: uuid.UUID
    version_number: int
    status: str
    compensation_enabled: bool
    fields: list[FormFieldRead] = Field(default_factory=list)
