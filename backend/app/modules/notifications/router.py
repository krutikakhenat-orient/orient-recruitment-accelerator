"""Notifications HTTP router (thin).

Permissions: reading channel status needs any signed-in user; reading templates and the
delivery log needs candidate.view; sending needs application.review for that campaign;
editing a template needs campaign.approve (HR sign-off on message wording).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.core.errors import ValidationError
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    DeliveryRead,
    NotificationStatusRead,
    SendRequest,
    TemplateRead,
    TemplateUpdate,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/status", response_model=NotificationStatusRead)
def channel_status(
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> NotificationStatusRead:
    """Whether email / WhatsApp are connected, simulated, or still placeholders."""
    return service.status(settings)


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[TemplateRead]:
    require_permission(actor, Permission.CANDIDATE_VIEW)
    return service.list_templates(db, actor.organisation_id)


@router.put("/templates/{key}", response_model=TemplateRead)
def update_template(
    key: str,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> TemplateRead:
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.save_template(
        db, actor=actor, key=key, subject=payload.subject, body=payload.body
    )


@router.get("/deliveries", response_model=list[DeliveryRead])
def list_deliveries(
    application_id: uuid.UUID | None = Query(default=None),
    campaign_id: uuid.UUID | None = Query(default=None),
    onboarding_case_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[DeliveryRead]:
    """The message log for one application or campaign (what was sent, simulated or failed)."""
    if application_id is None and campaign_id is None and onboarding_case_id is None:
        raise ValidationError("Pass application_id, campaign_id or onboarding_case_id")
    if application_id is not None:
        application = application_service.get_application(db, actor.organisation_id, application_id)
        require_campaign_permission(actor, Permission.CANDIDATE_VIEW, application.campaign_id)
    elif campaign_id is not None:
        require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    else:
        require_permission(actor, Permission.CANDIDATE_VIEW)
    rows = service.list_deliveries(
        db, actor.organisation_id, application_id=application_id, campaign_id=campaign_id,
        onboarding_case_id=onboarding_case_id,
    )
    if application_id is None and campaign_id is None:
        rows = [r for r in rows if r.campaign_id in actor.assigned_campaign_ids]
    return [DeliveryRead.model_validate(r) for r in rows]


@router.post("/send", response_model=DeliveryRead, status_code=201)
def send(
    payload: SendRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DeliveryRead:
    """Send (or record, if no provider is connected) one templated message to a candidate."""
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(actor, Permission.APPLICATION_REVIEW, application.campaign_id)
    delivery = service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=application, template_key=payload.template_key, channel=payload.channel,
        context=_default_context(payload.template_key),
    )
    return DeliveryRead.model_validate(delivery)


def _default_context(template_key: str) -> dict[str, str]:
    """Neutral wording for manual sends where the caller supplies no specifics."""
    return {
        "role": "the role you applied for",
        "when": "to be confirmed",
        "where": "to be confirmed",
        "respond_by": "the date shared with you",
        "link": "",
        "documents": "",
    }
