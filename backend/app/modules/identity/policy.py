"""Authorisation policy: permission checks and object-level authorisation.

These functions are the single source of truth for "may this actor do X". They are
pure (no DB/HTTP) so they can be unit-tested exhaustively (Req 1.2, 1.3). Routers call
them via FastAPI dependencies; services call them directly for defence in depth.
"""

from __future__ import annotations

import uuid

from app.core.errors import PermissionDeniedError
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor


def has_permission(actor: AuthenticatedActor, permission: Permission) -> bool:
    return permission.value in actor.permissions


def require_permission(actor: AuthenticatedActor, permission: Permission) -> None:
    if not has_permission(actor, permission):
        raise PermissionDeniedError(f"Missing required permission: {permission.value}")


def can_access_campaign(actor: AuthenticatedActor, campaign_id: uuid.UUID) -> bool:
    """Object-level authorisation.

    A permission grant is only effective for a campaign the actor is explicitly
    assigned to (Req 1.2.3, 1.2.4). System configuration permission does NOT grant
    candidate-content access (Req 1.3.6); that is enforced where content is read.
    """
    return campaign_id in actor.assigned_campaign_ids


def require_campaign_access(actor: AuthenticatedActor, campaign_id: uuid.UUID) -> None:
    if not can_access_campaign(actor, campaign_id):
        raise PermissionDeniedError("Actor is not assigned to this campaign")


def require_campaign_permission(
    actor: AuthenticatedActor, permission: Permission, campaign_id: uuid.UUID
) -> None:
    """Combined check: hold the permission AND be assigned to the campaign."""
    require_permission(actor, permission)
    require_campaign_access(actor, campaign_id)
