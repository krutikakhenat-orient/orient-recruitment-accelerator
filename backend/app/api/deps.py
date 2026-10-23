"""Shared FastAPI dependencies: settings, DB session, authenticated actor, guards."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.identity.service import resolve_actor


def settings_dep() -> Settings:
    return get_settings()


def get_current_actor(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    authorization: str | None = Header(default=None),
) -> AuthenticatedActor:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    actor = resolve_actor(db, settings, token)
    request.state.actor_id = str(actor.user_id)
    return actor


def requires(permission: Permission) -> Callable[[AuthenticatedActor], AuthenticatedActor]:
    """Factory producing a dependency that enforces a global permission."""

    def _dep(actor: AuthenticatedActor = Depends(get_current_actor)) -> AuthenticatedActor:
        require_permission(actor, permission)
        return actor

    return _dep
