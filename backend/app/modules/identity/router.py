"""Identity & Access HTTP router (thin: validation + delegation only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, requires, settings_dep
from app.core.config import Settings
from app.core.correlation import get_correlation_id
from app.core.errors import AuthenticationError, error_envelope
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

# The refresh token for the browser app lives in an HttpOnly cookie (never readable by
# JavaScript, so XSS cannot steal it) scoped to the auth endpoints only. The short-lived
# access token stays in memory. This is what lets a hard refresh restore the session.
REFRESH_COOKIE = "ora_refresh"
_COOKIE_PATH = "/api/v1/auth"
# CSRF defence for the cookie-authenticated refresh: a cross-site page cannot add a custom
# header without a CORS preflight, which our restricted CORS policy rejects.
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "ora-web"


def _set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_seconds,
        path=_COOKIE_PATH,
        httponly=True,
        secure=settings.is_production_like,  # plain http is needed for localhost dev
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)

# MVP is single-organisation. The default organisation id is resolved at login time
# from the configured org; until Organisations CRUD lands, the seed creates one org
# and users carry its id. We look it up from the user's email within that org.


@router.post("/auth/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> TokenPair:
    # Organisation is resolved from the single active org for MVP.
    from app.modules.identity.repository import get_user_by_email  # local import avoids cycle
    from app.modules.organisations.repository import get_default_organisation

    org = get_default_organisation(db)
    _ = get_user_by_email  # referenced for clarity; service re-resolves within org
    tokens = service.authenticate(
        db,
        settings,
        organisation_id=org.id,
        email=payload.email,
        password=payload.password,
        totp_code=payload.totp_code,
    )
    _set_refresh_cookie(response, settings, tokens.refresh_token)
    return tokens


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> TokenPair | JSONResponse:
    """Exchange a refresh token for a new pair. The token comes from the request body (API
    clients) or, for the browser app, from the HttpOnly cookie. The cookie path additionally
    requires the CSRF header, and the cookie is rotated on every use."""
    body_token = payload.refresh_token if payload else None
    if body_token:
        return service.refresh(db, settings, body_token)

    cookie_token = request.cookies.get(REFRESH_COOKIE)
    if not cookie_token:
        raise AuthenticationError("Invalid refresh token")
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise AuthenticationError("Invalid refresh token")
    try:
        tokens = service.refresh(db, settings, cookie_token)
    except AuthenticationError as exc:
        # Return the error directly (not raise) so the cookie-clearing header survives:
        # an exception handler would build a fresh response and drop it. A dead cookie
        # should not be retried on every page load.
        failure = JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(
                code=exc.code, message=exc.message, correlation_id=get_correlation_id()
            ),
        )
        _clear_refresh_cookie(failure)
        return failure
    _set_refresh_cookie(response, settings, tokens.refresh_token)
    return tokens


@router.post("/auth/logout", status_code=204)
def logout() -> Response:
    """End the browser session by clearing the refresh cookie. Access tokens are short-lived
    and held in memory only, so they are discarded by the client."""
    out = Response(status_code=204)
    _clear_refresh_cookie(out)
    return out


@router.get("/auth/me", response_model=AuthenticatedActor)
def me(actor: AuthenticatedActor = Depends(get_current_actor)) -> AuthenticatedActor:
    return actor


def _user_read(user: object) -> UserRead:
    """Map a User ORM row to UserRead, including its role names (e.g. 'interview_panel').

    role_names is non-sensitive metadata used by UI pickers (it is never a password or
    candidate data). Roles are read from the user's UserRole rows."""
    from app.modules.identity.models import User

    assert isinstance(user, User)
    data = UserRead.model_validate(user)
    role_names = sorted({ur.role.name for ur in user.roles if ur.role is not None})
    return data.model_copy(update={"role_names": role_names})


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
    return _user_read(user)


@router.get("/users", response_model=list[UserRead])
def list_users(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[UserRead]:
    """List staff users in the organisation.

    Available to any authenticated staff member so the UI can offer a distinct approver for
    four-eyes actions and the interviewer picker. By default only ACTIVE users are returned
    (so pickers never offer a deactivated user). ``include_inactive=true`` (used by the admin
    user-management table, which also shows status) returns everyone. Returns only
    non-sensitive identity fields (no password hashes, no candidate data).
    """
    from app.modules.identity import repository as identity_repo

    users = identity_repo.list_users(
        db, actor.organisation_id, include_inactive=include_inactive
    )
    return [_user_read(u) for u in users]


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.USER_MANAGE)),
) -> Response:
    """Soft-delete (deactivate) a staff user. Requires user.manage.

    Non-destructive: the account is marked inactive and can no longer sign in or be selected
    as an interviewer, but the row and all existing relationships/history are preserved. An
    admin cannot delete their own account.
    """
    service.deactivate_user(
        db,
        organisation_id=actor.organisation_id,
        user_id=user_id,
        actor_id=actor.user_id,
    )
    return Response(status_code=204)
