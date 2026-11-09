"""Induction HTTP router (thin). Employee self-service induction surface.

Every endpoint that exposes induction content requires ``induction.view`` (held only by
RoleName.EMPLOYEE). The router performs auth/validation/serialization only and delegates
all logic to the service. Video bytes are served through this authenticated endpoint, not
via a public bucket URL (mirrors documents/router.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, requires
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.documents.storage import default_object_store
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.induction import repository as repo
from app.modules.induction import service
from app.modules.induction.schemas import (
    CompletionResult,
    InductionStatusRead,
    InductionVideoRead,
    InductionVideoUrl,
)

router = APIRouter(prefix="/api/v1/induction", tags=["induction"])


@router.get("/me", response_model=InductionStatusRead)
def get_my_induction(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InductionStatusRead:
    """Induction status for the current user (video presence + completion state)."""
    return service.get_current_induction(db, actor)


@router.get("/video", response_model=InductionVideoRead)
def get_induction_video(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.INDUCTION_VIEW)),
) -> InductionVideoRead:
    """Metadata for the active induction video, or 404 if none is configured."""
    video = repo.get_active_video(db, actor.organisation_id)
    if video is None:
        raise NotFoundError("No induction video is configured")
    return InductionVideoRead.model_validate(video)


@router.get("/video/url", response_model=InductionVideoUrl)
def get_induction_video_url(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.INDUCTION_VIEW)),
) -> InductionVideoUrl:
    """Short-lived signed link to the video, for stores that support it (S3).

    Serverless responses are size-limited, so large media is fetched straight from the
    private bucket with a signed GET link instead of streaming through the API. The caller
    is authenticated and holds ``induction.view``; the link is single-object, GET-only and
    expires quickly. Stores without signed links (local dev) return 404 and the client falls
    back to ``/video/stream``.
    """
    video = repo.get_active_video(db, actor.organisation_id)
    if video is None:
        raise NotFoundError("No induction video is configured")
    presign = getattr(default_object_store, "presigned_get_url", None)
    if presign is None:
        raise NotFoundError("Signed video links are not supported by this storage")
    ttl = get_settings().signed_url_ttl_seconds
    return InductionVideoUrl(
        url=presign(video.storage_key, video.content_type, ttl),
        content_type=video.content_type,
        expires_in_seconds=ttl,
    )


@router.get("/video/stream")
def stream_induction_video(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.INDUCTION_VIEW)),
) -> Response:
    """Serve the induction video bytes from the object store (authenticated)."""
    video = repo.get_active_video(db, actor.organisation_id)
    if video is None:
        raise NotFoundError("No induction video is configured")
    try:
        data = default_object_store.get(video.storage_key)
    except KeyError as exc:
        raise NotFoundError("Induction video content is unavailable") from exc
    return Response(
        content=data,
        media_type=video.content_type,
        headers={
            "Accept-Ranges": "bytes",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
        },
    )


@router.post("/complete", response_model=CompletionResult)
def complete_induction(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.INDUCTION_VIEW)),
) -> CompletionResult:
    """Mark the induction video complete for the current user (idempotent)."""
    return service.record_completion(db, actor)


@router.get("/certificate")
def get_induction_certificate(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.INDUCTION_VIEW)),
) -> Response:
    """Return the HTML completion certificate, or 4xx if not yet completed."""
    document, filename = service.build_certificate(db, actor)
    return Response(
        content=document,
        media_type="text/html; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
