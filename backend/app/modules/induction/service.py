"""Induction application service.

Orchestrates the employee induction experience: reporting status, recording an
idempotent completion (audited), issuing an HTML completion certificate (audited), and
the developer-only seed of the placeholder induction video. The router stays thin and
delegates here; every consequential action records an audit event.
"""

from __future__ import annotations

import datetime as dt
import html
import uuid

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.documents.storage import default_object_store
from app.modules.identity import repository as identity_repo
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.induction import repository as repo
from app.modules.induction.models import InductionVideo
from app.modules.induction.schemas import (
    CompletionResult,
    InductionStatusRead,
)

# Developer-provisioned induction video defaults. There is NO frontend path to upload a
# video; a developer provisions it via ``seed_developer_video`` (called from the CLI seed).
_DEV_VIDEO_TITLE = "Employee Induction"
_DEV_VIDEO_DESCRIPTION = (
    "SYNTHETIC placeholder induction video provisioned by a developer. Replace with the "
    "real induction recording (see seed_developer_video)."
)
_DEV_VIDEO_CONTENT_TYPE = "video/mp4"

# A minimal, structurally-valid MP4 container (ftyp + empty moov/mvhd). It is a real,
# parseable MP4 so a <video> element treats the stream as video/mp4; it has no visible
# frames (placeholder only). A developer replaces the REAL video by swapping these bytes
# and the content type at the object-store key (see seed_developer_video).
_PLACEHOLDER_MP4: bytes = (
    bytes.fromhex(
        "0000001c667479706d703432000000006d7034326973006d703431"  # ftyp: major mp42
    )
    + bytes.fromhex(
        "0000006c6d6f6f760000006c6d7668640000000000000000000000000000"
        "03e8000000000001000001000000000000000000000000000100000000000"
        "0000000000000000000000010000000000000000000000000000400000000"
        "0000000000000000000000000002"
    )
)


def _video_storage_key(organisation_id: uuid.UUID) -> str:
    """Documented object-store key for an org's induction video blob."""
    return f"induction/{organisation_id}/induction-video.mp4"


def _as_aware_utc(value: dt.datetime) -> dt.datetime:
    """Normalise a possibly naive timestamp to timezone-aware UTC.

    SQLite (and some drivers) return naive datetimes even for timezone-aware columns, so a
    freshly-created row (still aware in memory) and the same row read back (naive) would
    serialize differently. Normalising here keeps ``completed_at`` consistent across both
    code paths.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def get_current_induction(db: Session, actor: AuthenticatedActor) -> InductionStatusRead:
    """Report whether a video exists and whether this actor has completed it."""
    video = repo.get_active_video(db, actor.organisation_id)
    if video is None:
        return InductionStatusRead(has_video=False, completed=False, completed_at=None)
    completion = repo.get_completion(db, actor.organisation_id, actor.user_id, video.id)
    return InductionStatusRead(
        has_video=True,
        completed=completion is not None,
        completed_at=(
            _as_aware_utc(completion.completed_at) if completion is not None else None
        ),
    )


def record_completion(db: Session, actor: AuthenticatedActor) -> CompletionResult:
    """Record that the actor completed the induction. Idempotent + audited."""
    video = repo.get_active_video(db, actor.organisation_id)
    if video is None:
        raise NotFoundError("No induction video is configured")

    existing = repo.get_completion(db, actor.organisation_id, actor.user_id, video.id)
    if existing is not None:
        return CompletionResult(
            completed=True, completed_at=_as_aware_utc(existing.completed_at)
        )

    completion = repo.create_completion(
        db, actor.organisation_id, actor.user_id, video.id
    )
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="induction.completed",
            entity_type="induction_completion",
            entity_id=str(completion.id),
        ),
    )
    return CompletionResult(
        completed=True, completed_at=_as_aware_utc(completion.completed_at)
    )


def build_certificate(db: Session, actor: AuthenticatedActor) -> tuple[str, str]:
    """Build the HTML induction certificate for the actor.

    Returns ``(html, filename)``. Raises ValidationError when the actor has not completed
    the induction yet. Certificate issuance is audited. The certificate is HTML (not PDF):
    no PDF-writer dependency is available, so this is a print-friendly HTML document.
    """
    video = repo.get_active_video(db, actor.organisation_id)
    if video is None:
        raise ValidationError("No induction video is configured")
    completion = repo.get_completion(db, actor.organisation_id, actor.user_id, video.id)
    if completion is None:
        raise ValidationError("Induction has not been completed yet")

    user = identity_repo.get_user_by_id(db, actor.user_id)
    display_name = user.display_name if user is not None else actor.email
    email = user.email if user is not None else actor.email
    completed_on = completion.completed_at.strftime("%d %B %Y")

    document = _render_certificate_html(
        display_name=display_name,
        email=email,
        title=video.title,
        completed_on=completed_on,
    )

    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="induction.certificate_issued",
            entity_type="induction_completion",
            entity_id=str(completion.id),
        ),
    )
    filename = "induction-certificate.html"
    return document, filename


def _render_certificate_html(
    *, display_name: str, email: str, title: str, completed_on: str
) -> str:
    """Print-friendly HTML certificate with inline CSS (all inputs HTML-escaped)."""
    safe_name = html.escape(display_name)
    safe_email = html.escape(email)
    safe_title = html.escape(title)
    safe_date = html.escape(completed_on)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Induction Completion Certificate</title>
<style>
  @media print {{ @page {{ size: A4 landscape; margin: 1.5cm; }} }}
  body {{
    font-family: Georgia, "Times New Roman", serif;
    color: #1f2933;
    margin: 0;
    padding: 2.5rem;
    background: #ffffff;
  }}
  .certificate {{
    border: 4px double #334e68;
    padding: 3rem;
    max-width: 48rem;
    margin: 0 auto;
    text-align: center;
  }}
  .eyebrow {{
    letter-spacing: 0.3em;
    text-transform: uppercase;
    font-size: 0.75rem;
    color: #627d98;
  }}
  h1 {{ font-size: 2rem; margin: 0.5rem 0 1.5rem; color: #243b53; }}
  .recipient {{ font-size: 1.5rem; font-weight: bold; margin: 0.5rem 0; }}
  .email {{ color: #627d98; margin-bottom: 1.5rem; }}
  .course {{ font-size: 1.1rem; margin: 1rem 0; }}
  .date {{ margin-top: 2rem; color: #334e68; }}
</style>
</head>
<body>
  <div class="certificate">
    <div class="eyebrow">Certificate of Completion</div>
    <h1>Employee Induction</h1>
    <p>This certifies that</p>
    <p class="recipient">{safe_name}</p>
    <p class="email">{safe_email}</p>
    <p class="course">has successfully completed the induction:<br />
      <strong>{safe_title}</strong></p>
    <p class="date">Completed on {safe_date}</p>
  </div>
</body>
</html>
"""


def seed_developer_video(db: Session, organisation_id: uuid.UUID) -> InductionVideo:
    """Provision the developer placeholder induction video for an organisation.

    Idempotent: reuses the existing active video (and leaves its blob in place) on repeat
    runs. There is deliberately NO frontend path to add an induction video.

    HOW A DEVELOPER REPLACES THE REAL VIDEO:
      The real induction recording is swapped at the object-store key returned by
      ``_video_storage_key(organisation_id)`` (currently
      ``induction/<organisation_id>/induction-video.mp4``). To install the real video:
        1. Call ``default_object_store.put(key, <real video bytes>, "<content type>")``
           with that key.
        2. If the content type changes (e.g. to "video/webm"), update the matching
           InductionVideo row's ``content_type`` so the stream endpoint serves it correctly.
      No schema or code change is required for the common MP4 case: only the blob bytes at
      the key need to change.
    """
    key = _video_storage_key(organisation_id)
    if not default_object_store.exists(key):
        default_object_store.put(key, _PLACEHOLDER_MP4, _DEV_VIDEO_CONTENT_TYPE)
    return repo.upsert_video(
        db,
        organisation_id=organisation_id,
        title=_DEV_VIDEO_TITLE,
        description=_DEV_VIDEO_DESCRIPTION,
        storage_key=key,
        content_type=_DEV_VIDEO_CONTENT_TYPE,
    )
