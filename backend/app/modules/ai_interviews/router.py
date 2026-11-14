"""AI interview HTTP router (thin). Three audiences:

* staff        authenticated, campaign-scoped (object-level authorisation)
* candidate    public, authenticated only by a single-use link token sent in the BODY
               (never in the URL path, so it does not end up in access logs)
* agent        public webhook, authenticated by an HMAC signature
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.core.errors import ValidationError
from app.db.session import get_db
from app.modules.ai_interviews import recording, service
from app.modules.ai_interviews.agent_client import InterviewAgentClient, build_agent_client
from app.modules.ai_interviews.models import AiInterviewRecording, AiInterviewSession
from app.modules.ai_interviews.schemas import (
    AiInterviewRead,
    ApproveRequest,
    ApproveResponse,
    PublicPreviewResponse,
    PublicStartRequest,
    PublicStartResponse,
    PublicTokenRequest,
    QuestionRead,
    RecordingChunkResult,
    RecordingPlaybackRead,
    RecordingRead,
    RecordingTokenRequest,
    RetryRequest,
    TranscriptRead,
    TranscriptTurnRead,
)
from app.modules.applications import service as application_service
from app.modules.documents.storage import ObjectStore, default_object_store
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/ai-interviews", tags=["ai-interviews"])


def get_agent_client(settings: Settings = Depends(settings_dep)) -> InterviewAgentClient:
    return build_agent_client(settings)


def get_object_store() -> ObjectStore:
    """Where video evidence is kept (private S3 in AWS, local disk in dev). Overridable in
    tests."""
    return default_object_store


def _read(row: AiInterviewSession) -> AiInterviewRead:
    questions = [
        QuestionRead(
            id=q["id"],
            text=q["text"],
            competency=q.get("competency", "general"),
            source=q.get("source", "job_description"),
            evidence_ref=q.get("evidence_ref"),
        )
        for q in (row.question_set or {}).get("questions", [])
    ]
    return AiInterviewRead(
        id=row.id,
        application_id=row.application_id,
        campaign_id=row.campaign_id,
        status=row.status,
        role_title=row.role_title,
        questions=questions,
        generated_by=row.generated_by,
        approved_at=row.approved_at,
        link_expires_at=row.link_expires_at,
        consent_given_at=row.consent_given_at,
        start_count=row.start_count,
        completed_at=row.completed_at,
        end_reason=row.end_reason,
        has_result=row.summary is not None,
        summary=row.summary,
        created_at=row.created_at,
    )


# ------------------------------------------------------------------ staff


@router.get("/campaigns/{campaign_id}/sessions", response_model=list[AiInterviewRead])
def list_campaign_sessions(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[AiInterviewRead]:
    """Requires candidate.view for the campaign. The transcript is never in this list."""
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    rows = service.list_sessions(db, organisation_id=actor.organisation_id, campaign_id=campaign_id)
    return [_read(r) for r in rows]


@router.post("/applications/{application_id}", response_model=AiInterviewRead, status_code=201)
def create_draft_for_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AiInterviewRead:
    """Manually offer an AI interview to an application (for candidates the automatic hook did
    not cover). Requires interview.schedule for the application's campaign."""
    service.require_enabled(settings)
    application = application_service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, application.campaign_id)
    row = service.ensure_draft(db, application=application, actor_id=actor.user_id)
    return _read(row)


@router.post("/sessions/{session_id}/plan", response_model=AiInterviewRead)
def plan_questions(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    client: InterviewAgentClient = Depends(get_agent_client),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AiInterviewRead:
    """Ask the agent to draft questions from the JD and resume. Requires interview.schedule."""
    row = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.INTERVIEW_SCHEDULE, row.campaign_id)
    row = service.plan_questions(
        db, settings=settings, client=client, actor=actor, session_id=session_id
    )
    return _read(row)


@router.post("/sessions/{session_id}/approve", response_model=ApproveResponse)
def approve_questions(
    session_id: uuid.UUID,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ApproveResponse:
    """A human approves the questions and the candidate link is issued (shown once).
    Requires interview.approve for the campaign."""
    row = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.INTERVIEW_APPROVE, row.campaign_id)
    row, token = service.approve_and_issue_link(
        db, settings=settings, actor=actor, session_id=session_id, payload=payload
    )
    assert row.link_expires_at is not None
    return ApproveResponse(
        session=_read(row),
        link_url=service.link_url_for(settings, token),
        link_expires_at=row.link_expires_at,
    )


@router.post("/sessions/{session_id}/link", response_model=ApproveResponse)
def reissue_link(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ApproveResponse:
    """Issue a fresh link (the previous one stops working). Requires interview.approve."""
    row = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.INTERVIEW_APPROVE, row.campaign_id)
    row, token = service.reissue_link(
        db, settings=settings, actor=actor, session_id=session_id
    )
    assert row.link_expires_at is not None
    return ApproveResponse(
        session=_read(row),
        link_url=service.link_url_for(settings, token),
        link_expires_at=row.link_expires_at,
    )


@router.post("/sessions/{session_id}/retry", response_model=ApproveResponse, status_code=201)
def retry_interview(
    session_id: uuid.UUID,
    payload: RetryRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ApproveResponse:
    """Offer another attempt after a finished interview. The finished attempt and its result
    are kept; a new attempt with the same approved questions and a fresh link is created
    (link shown once). Requires interview.approve for the campaign and a reason."""
    previous = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.INTERVIEW_APPROVE, previous.campaign_id)
    row, token = service.retry_interview(
        db, settings=settings, actor=actor, session_id=session_id, reason=payload.reason
    )
    assert row.link_expires_at is not None
    return ApproveResponse(
        session=_read(row),
        link_url=service.link_url_for(settings, token),
        link_expires_at=row.link_expires_at,
    )


@router.post("/sessions/{session_id}/revoke", response_model=AiInterviewRead)
def revoke_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AiInterviewRead:
    """Withdraw an unfinished interview and kill its link. Requires interview.approve."""
    row = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.INTERVIEW_APPROVE, row.campaign_id)
    return _read(service.revoke(db, actor=actor, session_id=session_id))


@router.get("/sessions/{session_id}/transcript", response_model=TranscriptRead)
def get_transcript(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> TranscriptRead:
    """The raw transcript is personal data: requires candidate.view_pii for the campaign and
    every read is audited."""
    row = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW_PII, row.campaign_id)
    service.record_transcript_view(db, actor=actor, row=row)
    turns = [
        TranscriptTurnRead(
            speaker=t.get("speaker", ""),
            text=t.get("text", ""),
            question_id=t.get("question_id"),
            at=str(t["at"]) if t.get("at") is not None else None,
            flags=list(t.get("flags") or []),
        )
        for t in (row.transcript or [])
    ]
    return TranscriptRead(session_id=row.id, turns=turns)


def _recording_read(row: AiInterviewRecording) -> RecordingRead:
    return RecordingRead(
        id=row.id,
        session_id=row.session_id,
        attempt_start=row.attempt_start,
        status=row.status,
        content_type=row.content_type,
        bytes_total=row.bytes_total,
        consent_given_at=row.consent_given_at,
        finished_at=row.finished_at,
        delete_after=row.delete_after,
        created_at=row.created_at,
    )


@router.get("/sessions/{session_id}/recordings", response_model=list[RecordingRead])
def list_session_recordings(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[RecordingRead]:
    """Video evidence for one interview (metadata only). Requires candidate.view_pii."""
    row = service.get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW_PII, row.campaign_id)
    rows = recording.list_recordings(
        db, organisation_id=actor.organisation_id, session_id=session_id
    )
    return [_recording_read(r) for r in rows]


def _authorised_recording(
    db: Session, actor: AuthenticatedActor, recording_id: uuid.UUID
) -> AiInterviewRecording:
    rec = recording.get_recording(
        db, organisation_id=actor.organisation_id, recording_id=recording_id
    )
    # Object-level check against the recording's own campaign (not a caller-supplied id).
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW_PII, rec.campaign_id)
    return rec


@router.get("/recordings/{recording_id}/playback", response_model=RecordingPlaybackRead)
def recording_playback(
    recording_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    store: ObjectStore = Depends(get_object_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> RecordingPlaybackRead:
    """How to play the video. Requires candidate.view_pii; viewing is audited.

    With S3, returns a short-lived signed GET link (serverless responses are too small to
    carry video). Otherwise returns no URL and the client uses ``/stream``, which audits."""
    rec = _authorised_recording(db, actor, recording_id)
    presign = getattr(store, "presigned_get_url", None)
    if presign is None:
        return RecordingPlaybackRead(content_type=rec.content_type)
    key = recording.prepare_playback(db, store=store, actor=actor, row=rec)
    ttl = settings.signed_url_ttl_seconds
    return RecordingPlaybackRead(
        url=presign(key, rec.content_type, ttl),
        content_type=rec.content_type,
        expires_in_seconds=ttl,
    )


@router.get("/recordings/{recording_id}/stream")
def recording_stream(
    recording_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> Response:
    """The video bytes (local storage). Requires candidate.view_pii; viewing is audited."""
    rec = _authorised_recording(db, actor, recording_id)
    key = recording.prepare_playback(db, store=store, actor=actor, row=rec)
    return Response(
        content=store.get(key),
        media_type=rec.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
        },
    )


# ------------------------------------------------------------------ candidate (public)


@router.post("/public/preview", response_model=PublicPreviewResponse)
def public_preview(
    payload: PublicTokenRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> PublicPreviewResponse:
    """What the candidate sees before consenting. Exposes only the role title and the notice."""
    row = service.public_preview(db, settings=settings, token=payload.token)
    offered = recording.video_enabled(settings)
    return PublicPreviewResponse(
        role_title=row.role_title,
        status=row.status,
        notice_version=service.NOTICE_VERSION,
        notice_text=service.NOTICE_TEXT,
        max_minutes=30,
        video_recording_offered=offered,
        video_notice_version=recording.VIDEO_NOTICE_VERSION if offered else None,
        video_notice_text=recording.video_notice_text(settings) if offered else None,
    )


@router.post("/public/start", response_model=PublicStartResponse)
def public_start(
    payload: PublicStartRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    client: InterviewAgentClient = Depends(get_agent_client),
) -> PublicStartResponse:
    """Record consent, prepare the agent, and return how the browser connects to it."""
    row, join_token, ws_url, recording_token = service.public_start(
        db,
        settings=settings,
        client=client,
        token=payload.token,
        consent=payload.consent,
        notice_version=payload.notice_version,
        video_consent=payload.video_consent,
        video_notice_version=payload.video_notice_version,
    )
    return PublicStartResponse(
        interview_id=row.id,
        ws_url=ws_url,
        join_token=join_token,
        recording_token=recording_token,
        recording_max_chunk_bytes=(
            settings.ai_interview_video_max_chunk_bytes if recording_token else None
        ),
    )


# Fixed random bytes (not compressible, so the measured speed is real). Made once per process.
_SPEED_SAMPLE = os.urandom(256 * 1024)
_SPEED_UPLOAD_LIMIT = 512 * 1024


@router.get("/public/network-check")
def network_check(size: Literal["ping", "sample"] = "ping") -> Response:
    """Pre-interview connection check (public, no data). ``ping`` measures delay; ``sample``
    returns 256 KB to time the download. Responses are never cached."""
    body = b"ok" if size == "ping" else _SPEED_SAMPLE
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/public/network-check")
async def network_check_upload(request: Request) -> dict[str, int]:
    """Times an upload: reads up to 512 KB and discards it. Nothing is stored."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > _SPEED_UPLOAD_LIMIT:
        raise ValidationError("Sample too large.")
    received = 0
    async for part in request.stream():
        received += len(part)
        if received > _SPEED_UPLOAD_LIMIT:
            raise ValidationError("Sample too large.")
    return {"received": received}


@router.post("/public/recording/chunk", response_model=RecordingChunkResult)
async def upload_recording_chunk(
    request: Request,
    seq: int = Query(ge=0, lt=recording.MAX_CHUNKS),
    x_recording_token: str = Header(default="", max_length=200),
    content_type: str = Header(default=""),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    store: ObjectStore = Depends(get_object_store),
) -> RecordingChunkResult:
    """One ~10 s piece of the candidate's video evidence (raw WebM/MP4 bytes in the body).

    Public, authorised only by the per-recording upload token in a header (never the URL, so
    it stays out of access logs). The body size is checked before it is read in full."""
    declared = request.headers.get("content-length")
    limit = settings.ai_interview_video_max_chunk_bytes
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ValidationError("Chunk too large.")
    data = await request.body()
    row = recording.store_chunk(
        db,
        settings=settings,
        store=store,
        token=x_recording_token,
        seq=seq,
        data=data,
        content_type=content_type,
    )
    return RecordingChunkResult(chunk_count=row.chunk_count)


@router.post("/public/recording/finish", response_model=RecordingChunkResult)
def finish_recording(
    payload: RecordingTokenRequest,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
) -> RecordingChunkResult:
    """The browser stopped recording; the upload token stops working."""
    row = recording.finish_recording(db, store=store, token=payload.recording_token)
    return RecordingChunkResult(chunk_count=row.chunk_count)


# ------------------------------------------------------------------ agent webhook


@router.post("/webhook", status_code=202)
async def agent_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    x_interview_timestamp: str | None = Header(default=None),
    x_interview_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receives the finished interview from the agent. Authenticated by HMAC, not a user."""
    body = await request.body()
    row = service.ingest_agent_record(
        db,
        settings=settings,
        body=body,
        timestamp=x_interview_timestamp,
        signature=x_interview_signature,
    )
    return {"status": "stored", "interview_id": str(row.id)}
