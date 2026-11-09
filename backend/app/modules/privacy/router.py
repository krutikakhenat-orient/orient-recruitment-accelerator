"""Privacy & retention HTTP router (thin). Requires privacy_request.manage /
system.configure as appropriate."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.candidates.models import Candidate
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.privacy import service
from app.modules.privacy.models import (
    PrivacyRequest,
    PrivacyRequestType,
    RecordCategory,
    RetentionActionType,
)

router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])


class PrivacyRequestCreate(BaseModel):
    # Identify the person by internal id OR by the email they used to apply.
    candidate_id: uuid.UUID | None = None
    candidate_email: EmailStr | None = None
    request_type: PrivacyRequestType
    detail: str | None = None

    @model_validator(mode="after")
    def _one_identifier(self) -> PrivacyRequestCreate:
        if self.candidate_id is None and self.candidate_email is None:
            raise ValueError("Provide candidate_id or candidate_email")
        return self


class PrivacyRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    request_type: str
    status: str


class PrivacyRequestListItem(PrivacyRequestRead):
    # Masked on purpose: managing requests must not expose a candidate's contact details.
    candidate_email_masked: str
    detail: str | None
    created_at: dt.datetime
    completed_at: dt.datetime | None


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


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
    candidate_id = payload.candidate_id
    if candidate_id is None:
        email = str(payload.candidate_email).strip().lower()
        candidate_id = db.execute(
            select(Candidate.id).where(
                Candidate.organisation_id == actor.organisation_id,
                Candidate.email == email,
            )
        ).scalars().first()
        if candidate_id is None:
            raise NotFoundError("No candidate found with that email address")
    request = service.create_privacy_request(
        db, organisation_id=actor.organisation_id, candidate_id=candidate_id,
        request_type=payload.request_type, detail=payload.detail, actor_id=actor.user_id,
    )
    return PrivacyRequestRead.model_validate(request)


@router.get("/requests", response_model=list[PrivacyRequestListItem])
def list_requests(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.PRIVACY_REQUEST_MANAGE)),
) -> list[PrivacyRequestListItem]:
    """Privacy requests with the candidate's email masked (no candidate content exposed)."""
    rows = db.execute(
        select(PrivacyRequest, Candidate.email)
        .join(Candidate, Candidate.id == PrivacyRequest.candidate_id)
        .where(PrivacyRequest.organisation_id == actor.organisation_id)
        .order_by(PrivacyRequest.created_at.desc())
        .limit(200)
    ).all()
    return [
        PrivacyRequestListItem(
            id=r.id, candidate_id=r.candidate_id, request_type=r.request_type, status=r.status,
            candidate_email_masked=_mask_email(email), detail=r.detail,
            created_at=r.created_at, completed_at=r.completed_at,
        )
        for r, email in rows
    ]


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
