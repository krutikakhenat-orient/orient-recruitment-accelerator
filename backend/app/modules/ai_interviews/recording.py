"""Video EVIDENCE for the AI voice interview (optional, consented, human review only).

What this does
    The candidate's browser records their camera and microphone during the interview and
    uploads it in ~10 s chunks. A Recruiter Admin can later play it back as evidence.

What this deliberately does NOT do (responsible-ai.md, product.md)
    No analysis of any kind: no face, gaze, emotion, appearance or "proctoring" detection.
    The video never feeds a score, flag, ranking or decision, and the AI agent never sees it.

Safeguards
    * Off unless ``ai_interview_video_enabled``. Needs its OWN consent, separate from the
      interview consent; a candidate who declines still takes the voice interview.
    * Uploads are authorised by a per-recording upload token (only its hash is stored). It is
      bound to one recording, expires, and stops working once the upload finishes.
    * Chunks are size-limited, the first one must look like a WebM/MP4 file, and the total
      per recording is capped.
    * Playback requires candidate.view_pii for the campaign and every view is audited.
    * Deleted after the retention period by ``purge_expired_recordings`` (audited).
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.ai_interviews.models import (
    AiInterviewRecording,
    AiInterviewSession,
    AiInterviewStatus,
    RecordingStatus,
)
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.documents.storage import ObjectStore
from app.modules.identity.schemas import AuthenticatedActor

log = logging.getLogger(__name__)

VIDEO_NOTICE_VERSION = "ai-interview-video-notice-v1"
VIDEO_NOTICE_TEXT = (
    "With your permission, your camera and microphone are also recorded during this "
    "interview. The video is kept only as evidence of the interview for a person to review "
    "if needed. It is never analysed by software and is not used to assess you. Only "
    "authorised hiring staff can watch it, every viewing is logged, and it is deleted after "
    "{days} days. You can say no and still take the interview by voice."
)

ALLOWED_CONTENT_TYPES = frozenset({"video/webm", "video/mp4"})
MAX_CHUNKS = 2000  # 2000 x 10 s is far beyond the interview's 30-minute limit
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"  # first bytes of every WebM/Matroska file
_ASSEMBLE_WORKERS = 8


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _hash(token: str) -> str:
    from app.modules.ai_interviews.service import hash_token

    return hash_token(token)


def video_enabled(settings: Settings) -> bool:
    return settings.ai_interview_enabled and settings.ai_interview_video_enabled


def video_notice_text(settings: Settings) -> str:
    return VIDEO_NOTICE_TEXT.format(days=settings.ai_interview_video_retention_days)


def _chunk_key(row: AiInterviewRecording, seq: int) -> str:
    return f"{row.storage_prefix}/chunk-{seq:06d}"


def _extension(content_type: str) -> str:
    return "mp4" if content_type == "video/mp4" else "webm"


def _audit(
    db: Session,
    row: AiInterviewRecording,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    reason: str | None = None,
    security_context: str | None = None,
) -> None:
    record_event(
        db,
        AuditEventWrite(
            organisation_id=row.organisation_id,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            entity_type="ai_interview_recording",
            entity_id=str(row.id),
            new_state_ref=row.status,
            reason=reason,
            security_context=security_context,
        ),
    )


# --------------------------------------------------------------------------- candidate


def start_recording(
    db: Session, *, settings: Settings, session: AiInterviewSession
) -> tuple[AiInterviewRecording, str]:
    """Create the recording for this start of the interview. Returns (row, upload_token).

    Called only after the candidate gave the separate video consent."""
    now = _now()
    token = secrets.token_urlsafe(32)
    rec_id = uuid.uuid4()
    row = AiInterviewRecording(
        id=rec_id,
        organisation_id=session.organisation_id,
        session_id=session.id,
        campaign_id=session.campaign_id,
        attempt_start=session.start_count,
        status=RecordingStatus.RECORDING.value,
        consent_notice_version=VIDEO_NOTICE_VERSION,
        consent_given_at=now,
        upload_token_hash=_hash(token),
        upload_expires_at=now
        + dt.timedelta(seconds=settings.ai_interview_video_upload_window_seconds),
        content_type="video/webm",
        storage_prefix=f"ai-interview-recordings/{session.organisation_id}/{session.id}/{rec_id}",
        delete_after=now + dt.timedelta(days=settings.ai_interview_video_retention_days),
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        row,
        "ai_interview.video_recording_started",
        actor_role="candidate",
        reason=f"video consent {VIDEO_NOTICE_VERSION}",
        security_context="candidate_consent",
    )
    return row, token


def _recording_for_upload(db: Session, token: str) -> AiInterviewRecording:
    """Resolve an upload token. Every failure looks the same, so tokens cannot be probed."""
    invalid = NotFoundError("This recording upload is not valid.")
    if not token or len(token) > 200:
        raise invalid
    row = db.execute(
        select(AiInterviewRecording).where(AiInterviewRecording.upload_token_hash == _hash(token))
    ).scalars().first()
    if row is None or row.status != RecordingStatus.RECORDING.value:
        raise invalid
    if _aware(row.upload_expires_at) < _now():
        raise invalid
    session = db.get(AiInterviewSession, row.session_id)
    if session is None or session.status == AiInterviewStatus.REVOKED.value:
        raise invalid
    return row


def _looks_like_video(data: bytes, content_type: str) -> bool:
    if content_type == "video/webm":
        return data[:4] == _EBML_MAGIC
    return data[4:8] == b"ftyp"  # ISO base media (MP4)


def store_chunk(
    db: Session,
    *,
    settings: Settings,
    store: ObjectStore,
    token: str,
    seq: int,
    data: bytes,
    content_type: str,
) -> AiInterviewRecording:
    """Store one chunk. Re-sending the same ``seq`` (a network retry) overwrites it."""
    row = _recording_for_upload(db, token)
    base_type = content_type.split(";", 1)[0].strip().lower()
    if base_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError("Unsupported video format.")
    if not 0 <= seq < MAX_CHUNKS:
        raise ValidationError("Chunk number out of range.")
    if not data:
        raise ValidationError("Empty chunk.")
    if len(data) > settings.ai_interview_video_max_chunk_bytes:
        raise ValidationError("Chunk too large.")
    if seq == 0:
        # Security: only the first chunk carries a file header; check it so arbitrary
        # files cannot be stored under a video recording.
        if not _looks_like_video(data, base_type):
            raise ValidationError("This does not look like a video recording.")
        row.content_type = base_type
    elif base_type != row.content_type:
        raise ValidationError("Video format changed during the recording.")

    key = _chunk_key(row, seq)
    is_new = not store.exists(key)
    if is_new and row.bytes_total + len(data) > settings.ai_interview_video_max_total_bytes:
        raise ConflictError("The recording has reached its size limit.")
    store.put(key, data, row.content_type)
    if is_new:
        row.bytes_total += len(data)
    row.chunk_count = max(row.chunk_count, seq + 1)
    db.flush()
    return row


def finish_recording(
    db: Session, *, store: ObjectStore, token: str
) -> AiInterviewRecording:
    """The browser stopped recording. Closes the upload and prepares the playable file."""
    row = _recording_for_upload(db, token)
    _complete(db, row)
    try:
        _assemble(store, row)
    except Exception as exc:  # noqa: BLE001 - playback retries assembly; never fail the candidate
        log.warning("recording_assembly_deferred", extra={"error": type(exc).__name__})
    db.flush()
    return row


def _complete(db: Session, row: AiInterviewRecording) -> None:
    row.status = RecordingStatus.COMPLETE.value
    row.finished_at = row.finished_at or _now()
    row.upload_token_hash = None  # the upload token stops working
    db.flush()
    _audit(db, row, "ai_interview.video_recording_finished", actor_role="candidate")


def _assemble(store: ObjectStore, row: AiInterviewRecording) -> str:
    """Join the chunks into one playable file (once) and remove the chunks."""
    if row.assembled_key and store.exists(row.assembled_key):
        return row.assembled_key
    keys = [_chunk_key(row, seq) for seq in range(row.chunk_count)]
    with ThreadPoolExecutor(max_workers=_ASSEMBLE_WORKERS) as pool:
        parts = list(pool.map(lambda k: store.get(k) if store.exists(k) else b"", keys))
    data = b"".join(parts)
    if not data:
        raise NotFoundError("This recording has no video.")
    target = f"{row.storage_prefix}/recording.{_extension(row.content_type)}"
    store.put(target, data, row.content_type)
    row.assembled_key = target
    for key in keys:
        store.delete(key)
    return target


# --------------------------------------------------------------------------- staff


def list_recordings(
    db: Session, *, organisation_id: uuid.UUID, session_id: uuid.UUID
) -> list[AiInterviewRecording]:
    stmt = (
        select(AiInterviewRecording)
        .where(
            AiInterviewRecording.organisation_id == organisation_id,
            AiInterviewRecording.session_id == session_id,
        )
        .order_by(AiInterviewRecording.created_at.asc())
    )
    return list(db.execute(stmt).scalars())


def get_recording(
    db: Session, *, organisation_id: uuid.UUID, recording_id: uuid.UUID
) -> AiInterviewRecording:
    row = db.get(AiInterviewRecording, recording_id)
    if row is None or row.organisation_id != organisation_id:
        raise NotFoundError("Recording not found")
    return row


def prepare_playback(
    db: Session, *, store: ObjectStore, actor: AuthenticatedActor, row: AiInterviewRecording
) -> str:
    """Return the object key of the playable file and audit the viewing.

    The caller has already checked candidate.view_pii for the recording's campaign."""
    if row.status == RecordingStatus.DELETED.value:
        raise NotFoundError("This recording has been deleted under the retention policy.")
    if row.status == RecordingStatus.RECORDING.value:
        if _aware(row.upload_expires_at) >= _now():
            raise ConflictError("The interview is still being recorded. Try again when it ends.")
        _complete(db, row)  # the browser never said it finished (tab closed, network lost)
    key = _assemble(store, row)
    db.flush()
    _audit(
        db,
        row,
        "ai_interview.video_viewed",
        actor_id=actor.user_id,
        security_context="candidate_pii_access",
    )
    return key


# --------------------------------------------------------------------------- retention


def purge_expired_recordings(
    db: Session, *, store: ObjectStore, now: dt.datetime | None = None
) -> int:
    """Delete every recording past its retention date. Returns how many were deleted."""
    now = now or _now()
    # Compare in Python as well: SQLite stores these without a timezone.
    candidates = db.execute(
        select(AiInterviewRecording).where(
            AiInterviewRecording.status != RecordingStatus.DELETED.value
        )
    ).scalars()
    due = [row for row in candidates if _aware(row.delete_after) <= now]
    count = 0
    for row in due:
        keys = [_chunk_key(row, seq) for seq in range(row.chunk_count)]
        if row.assembled_key:
            keys.append(row.assembled_key)
        for key in keys:
            store.delete(key)
        row.status = RecordingStatus.DELETED.value
        row.deleted_at = now
        row.upload_token_hash = None
        row.assembled_key = None
        db.flush()
        _audit(
            db,
            row,
            "ai_interview.video_deleted",
            actor_role="system.retention",
            reason="retention period ended",
        )
        count += 1
    return count
