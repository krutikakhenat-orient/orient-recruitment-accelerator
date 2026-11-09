"""AI interview HTTP router (thin). Three audiences:

* staff        authenticated, campaign-scoped (object-level authorisation)
* candidate    public, authenticated only by a single-use link token sent in the BODY
               (never in the URL path, so it does not end up in access logs)
* agent        public webhook, authenticated by an HMAC signature
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.ai_interviews import service
from app.modules.ai_interviews.agent_client import InterviewAgentClient, build_agent_client
from app.modules.ai_interviews.models import AiInterviewSession
from app.modules.ai_interviews.schemas import (
    AiInterviewRead,
    ApproveRequest,
    ApproveResponse,
    PublicPreviewResponse,
    PublicStartRequest,
    PublicStartResponse,
    PublicTokenRequest,
    QuestionRead,
    RetryRequest,
    TranscriptRead,
    TranscriptTurnRead,
)
from app.modules.applications import service as application_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/ai-interviews", tags=["ai-interviews"])


def get_agent_client(settings: Settings = Depends(settings_dep)) -> InterviewAgentClient:
    return build_agent_client(settings)


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


# ------------------------------------------------------------------ candidate (public)


@router.post("/public/preview", response_model=PublicPreviewResponse)
def public_preview(
    payload: PublicTokenRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> PublicPreviewResponse:
    """What the candidate sees before consenting. Exposes only the role title and the notice."""
    row = service.public_preview(db, settings=settings, token=payload.token)
    return PublicPreviewResponse(
        role_title=row.role_title,
        status=row.status,
        notice_version=service.NOTICE_VERSION,
        notice_text=service.NOTICE_TEXT,
        max_minutes=30,
    )


@router.post("/public/start", response_model=PublicStartResponse)
def public_start(
    payload: PublicStartRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    client: InterviewAgentClient = Depends(get_agent_client),
) -> PublicStartResponse:
    """Record consent, prepare the agent, and return how the browser connects to it."""
    row, join_token, ws_url = service.public_start(
        db,
        settings=settings,
        client=client,
        token=payload.token,
        consent=payload.consent,
        notice_version=payload.notice_version,
    )
    return PublicStartResponse(interview_id=row.id, ws_url=ws_url, join_token=join_token)


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
