"""Identity & Access HTTP router (thin: validation + delegation only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, requires, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.identity import service
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import (
    AuthenticatedActor,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserRead,
)

router = APIRouter(prefix="/api/v1", tags=["identity"])

# MVP is single-organisation. The default organisation id is resolved at login time
# from the configured org; until Organisations CRUD lands, the seed creates one org
# and users carry its id. We look it up from the user's email within that org.


@router.post("/auth/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> TokenPair:
    # Organisation is resolved from the single active org for MVP.
    from app.modules.identity.repository import get_user_by_email  # local import avoids cycle
    from app.modules.organisations.repository import get_default_organisation

    org = get_default_organisation(db)
    _ = get_user_by_email  # referenced for clarity; service re-resolves within org
    return service.authenticate(
        db,
        settings,
        organisation_id=org.id,
        email=payload.email,
        password=payload.password,
        totp_code=payload.totp_code,
    )


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> TokenPair:
    return service.refresh(db, settings, payload.refresh_token)


@router.get("/auth/me", response_model=AuthenticatedActor)
def me(actor: AuthenticatedActor = Depends(get_current_actor)) -> AuthenticatedActor:
    return actor


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.USER_MANAGE)),
) -> UserRead:
    user = service.create_user(
        db,
        organisation_id=actor.organisation_id,
        data=payload,
        actor_id=actor.user_id,
    )
    return UserRead.model_validate(user)


@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[UserRead]:
    """List active staff users in the organisation.

    Available to any authenticated staff member so the UI can offer a distinct approver for
    four-eyes actions (threshold changes, rule-set approval). Returns only non-sensitive
    identity fields (no password hashes, no candidate data).
    """
    from app.modules.identity import repository as identity_repo

    users = identity_repo.list_users(db, actor.organisation_id)
    return [UserRead.model_validate(u) for u in users]


_ = uuid  # keep uuid import for type references in schemas
