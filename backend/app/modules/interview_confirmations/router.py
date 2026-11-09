"""Interview confirmation HTTP routers (thin).

Staff endpoints need interview.schedule for the invitation's campaign. The public endpoints
are authenticated only by the personal link token (a bearer secret that works once).
Rate limiting for public endpoints is not wired yet (placeholder, see docs/open-decisions.md).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interview_confirmations import service
from app.modules.interview_confirmations.schemas import (
    LinkIssued,
    LinkStatus,
    PublicPreview,
    PublicRespond,
    PublicResult,
    SuggestedSlot,
)
from app.modules.interviews.models import InterviewInvitation
from app.modules.notifications.schemas import DeliveryRead

router = APIRouter(prefix="/api/v1/interview-confirmations", tags=["interview-confirmations"])
_CHANNEL = Query(default="email", pattern="^(email|whatsapp)$")


def _invitation(
    db: Session, actor: AuthenticatedActor, invitation_id: uuid.UUID
) -> InterviewInvitation:
    invitation = service.get_invitation(db, actor.organisation_id, invitation_id)
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, invitation.campaign_id)
    return invitation


@router.post("/invitations/{invitation_id}/link", response_model=LinkIssued, status_code=201)
def issue_link(
    invitation_id: uuid.UUID,
    send: bool = Query(default=True),
    channel: str = _CHANNEL,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> LinkIssued:
    """Create the candidate's personal confirmation link (and send it, or just copy it)."""
    invitation = _invitation(db, actor, invitation_id)
    url, link, delivery = service.issue_link(
        db, settings=settings, actor=actor, invitation=invitation, send=send, channel=channel
    )
    return LinkIssued(
        url=url, expires_at=service.as_utc(link.expires_at),
        delivery=DeliveryRead.model_validate(delivery) if delivery else None,
    )


@router.post("/invitations/{invitation_id}/remind", response_model=DeliveryRead)
def remind(
    invitation_id: uuid.UUID,
    channel: str = _CHANNEL,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DeliveryRead:
    invitation = _invitation(db, actor, invitation_id)
    return DeliveryRead.model_validate(
        service.send_reminder(
            db, settings=settings, actor=actor, invitation=invitation, channel=channel
        )
    )


@router.get("/invitations/{invitation_id}/status", response_model=LinkStatus)
def status(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> LinkStatus:
    return service.link_status(db, _invitation(db, actor, invitation_id))


@router.get("/invitations/{invitation_id}/suggested-slots", response_model=list[SuggestedSlot])
def suggested_slots(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[SuggestedSlot]:
    invitation = _invitation(db, actor, invitation_id)
    return service.suggested_slots(db, actor.organisation_id, invitation)


@router.get("/public/{token}", response_model=PublicPreview)
def public_preview(token: str, db: Session = Depends(get_db)) -> PublicPreview:
    """What the candidate sees on their personal link (first name, role, time, place)."""
    return service.public_preview(db, token)


@router.post("/public/{token}/respond", response_model=PublicResult)
def public_respond(
    token: str,
    payload: PublicRespond,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> PublicResult:
    return service.public_respond(db, settings=settings, token=token, response=payload.response)
