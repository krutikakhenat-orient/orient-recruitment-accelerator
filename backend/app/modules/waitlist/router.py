"""Waitlist + re-evaluation HTTP router (thin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.waitlist import service
from app.modules.waitlist.service import ReevaluationTrigger

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"])


class WaitlistAddRequest(BaseModel):
    application_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=1000)
    screening_run_id: uuid.UUID | None = None
    eligibility_state: str = "needs_review"


class WaitlistRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    campaign_id: uuid.UUID
    reason: str
    status: str
    eligibility_state: str


class ReevaluateRequest(BaseModel):
    application_id: uuid.UUID
    trigger: ReevaluationTrigger
    reason: str = Field(min_length=1, max_length=1000)


class ReevaluateResponse(BaseModel):
    new_run_id: uuid.UUID
    previous_run_id: uuid.UUID | None
    result_changed: bool


@router.post("", response_model=WaitlistRecordRead, status_code=201)
def add_to_waitlist(
    payload: WaitlistAddRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> WaitlistRecordRead:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(actor, Permission.WAITLIST_MANAGE, application.campaign_id)
    record = service.add_to_waitlist(
        db, actor=actor, application=application, reason=payload.reason,
        screening_run_id=payload.screening_run_id,
        eligibility_state=payload.eligibility_state,
    )
    return WaitlistRecordRead.model_validate(record)


@router.post("/reevaluate", response_model=ReevaluateResponse, status_code=201)
def reevaluate(
    payload: ReevaluateRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ReevaluateResponse:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(actor, Permission.SCREENING_EXECUTE, application.campaign_id)
    result = service.reevaluate(
        db, actor=actor, application=application, trigger=payload.trigger,
        reason=payload.reason,
    )
    return ReevaluateResponse(
        new_run_id=result.new_run.id, previous_run_id=result.previous_run_id,
        result_changed=result.result_changed,
    )
