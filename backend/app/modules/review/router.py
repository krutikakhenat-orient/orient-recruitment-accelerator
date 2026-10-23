"""Human-review HTTP router (thin). Requires application.review + campaign authz."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.review import service
from app.modules.review.models import ReviewItem
from app.modules.review.schemas import (
    ReviewActionRead,
    ReviewActionRequest,
    ReviewItemRead,
)

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewItemRead])
def list_items(
    campaign_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[ReviewItemRead]:
    require_campaign_permission(actor, Permission.APPLICATION_REVIEW, campaign_id)
    items = service.list_open_items(db, actor.organisation_id, campaign_id)
    return [ReviewItemRead.model_validate(i) for i in items]


@router.post("/{review_item_id}/actions", response_model=ReviewActionRead, status_code=201)
def record_action(
    review_item_id: uuid.UUID,
    payload: ReviewActionRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ReviewActionRead:
    item = db.get(ReviewItem, review_item_id)
    if item is None or item.organisation_id != actor.organisation_id:
        raise NotFoundError("Review item not found")
    require_campaign_permission(actor, Permission.APPLICATION_REVIEW, item.campaign_id)
    action = service.record_action(
        db, organisation_id=actor.organisation_id, review_item_id=review_item_id,
        action_type=payload.action_type, reason=payload.reason, actor=actor,
        original_value=payload.original_value, corrected_value=payload.corrected_value,
        resolves_item=payload.resolves_item,
    )
    return ReviewActionRead.model_validate(action)
