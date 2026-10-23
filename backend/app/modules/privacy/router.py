"""Privacy & retention HTTP router (thin). Requires privacy_request.manage /
system.configure as appropriate."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.privacy import service
from app.modules.privacy.models import (
    PrivacyRequestType,
    RecordCategory,
    RetentionActionType,
)

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])


class PrivacyRequestCreate(BaseModel):
    candidate_id: uuid.UUID
    request_type: PrivacyRequestType
    detail: str | None = None


class PrivacyRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    request_type: str
    status: str


class RetentionPolicyCreate(BaseModel):
    category: RecordCategory
    retain_days: int = Field(ge=0)
    action_on_expiry: RetentionActionType


class RetentionPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    retain_days: int
    action_on_expiry: str


@router.post("/requests", response_model=PrivacyRequestRead, status_code=201)
def create_request(
    payload: PrivacyRequestCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.PRIVACY_REQUEST_MANAGE)),
) -> PrivacyRequestRead:
    request = service.create_privacy_request(
        db, organisation_id=actor.organisation_id, candidate_id=payload.candidate_id,
        request_type=payload.request_type, detail=payload.detail, actor_id=actor.user_id,
    )
    return PrivacyRequestRead.model_validate(request)


@router.post("/requests/{request_id}/complete", response_model=PrivacyRequestRead)
def complete_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.PRIVACY_REQUEST_MANAGE)),
) -> PrivacyRequestRead:
    request = service.complete_privacy_request(
        db, organisation_id=actor.organisation_id, request_id=request_id,
        actor_id=actor.user_id,
    )
    return PrivacyRequestRead.model_validate(request)


@router.post("/retention-policies", response_model=RetentionPolicyRead, status_code=201)
def set_retention_policy(
    payload: RetentionPolicyCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.SYSTEM_CONFIGURE)),
) -> RetentionPolicyRead:
    policy = service.set_retention_policy(
        db, organisation_id=actor.organisation_id, category=payload.category,
        retain_days=payload.retain_days, action_on_expiry=payload.action_on_expiry,
        actor_id=actor.user_id,
    )
    return RetentionPolicyRead.model_validate(policy)
