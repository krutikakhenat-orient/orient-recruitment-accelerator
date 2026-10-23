"""DEV-ONLY router. Disabled in production-like environments.

Provides conveniences for local evaluation that bypass the normal multi-role, multi-step
governance flow. These endpoints must never be available in staging/production.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.core.errors import PermissionDeniedError
from app.db.session import get_db
from app.modules.campaigns import service as campaign_service
from app.modules.campaigns.schemas import CampaignRead
from app.modules.dev import service as dev_service
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/dev", tags=["dev"])


def _guard_non_production(settings: Settings) -> None:
    if settings.is_production_like:
        # Behave as if the route does not exist in production-like environments.
        raise PermissionDeniedError("Dev endpoints are disabled in this environment")


@router.post("/campaigns/{campaign_id}/open-now", response_model=CampaignRead)
def open_campaign_now(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CampaignRead:
    """Create+approve all artifacts and drive the campaign to applications_open (dev only)."""
    _guard_non_production(settings)
    campaign = campaign_service.get_campaign(db, actor.organisation_id, campaign_id)
    updated = dev_service.open_campaign_now(
        db, campaign=campaign, caller_user_id=actor.user_id
    )
    return CampaignRead.model_validate(updated)
