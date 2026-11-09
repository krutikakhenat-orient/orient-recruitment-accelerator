"""Integrations HTTP router (thin). Read-only status for any signed-in staff user."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.integrations import service
from app.modules.integrations.service import IntegrationRead

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationRead])
def list_integrations(
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[IntegrationRead]:
    """Which external systems are connected, simulated, or still placeholders."""
    return service.list_integrations(settings)
