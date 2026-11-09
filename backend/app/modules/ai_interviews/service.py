"""AI interview application service.

Lifecycle (every step after PENDING_PLAN is a human or candidate action):

    screening finishes  ->  PENDING_PLAN      (cheap draft row; nothing sent anywhere)
    recruiter: plan     ->  QUESTIONS_READY   (agent drafts questions from JD + resume)
    recruiter: approve  ->  APPROVED          (human approves; single-use candidate link issued)
    candidate: consent  ->  IN_PROGRESS       (agent prepared; browser connects to the agent)
    agent webhook       ->  COMPLETED         (advisory summary + transcript stored)

Guarantees (responsible-ai.md / product.md):
  * The agent is advisory. This module never changes an application's state, never stores or
    derives a score/verdict, and the platform works with the feature switched off.
  * No auto-invite: a link only exists after a human approved the questions.
  * Only an opaque reference leaves the platform (never name/email/phone). Emails and phone
    numbers are also stripped from resume text before it is sent for question planning.
  * Documents are untrusted: agent output is schema-validated before it is stored.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.modules.ai_interviews.agent_client import (
    AgentUnavailableError,
    InterviewAgentClient,
    runtime_session_id_for,
)
from app.modules.ai_interviews.models import (
    LINK_ACTIVE_STATUSES,
    LIVE_STATUSES,
    AiInterviewSession,
    AiInterviewStatus,
)
from app.modules.ai_interviews.schemas import (
    AgentRecordModel,
    ApproveRequest,
    QuestionSetModel,
)
from app.modules.applications.models import Application
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.schemas import AuthenticatedActor

NOTICE_VERSION = "ai-interview-notice-v1"
NOTICE_TEXT = (
    "This is an automated voice interview run by an AI assistant. It will ask you questions "
    "about your application for this role. Your spoken answers are converted to text, "
    "stored as a transcript, and summarised to help a human reviewer. The AI does not decide "
    "whether you are hired: people review the transcript and make every decision. "
    "Please do not share health, religion, family, age or other highly personal details; "
    "they are not used to assess you. You can stop at any time, and you can type your "
    "answers instead of speaking."
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().\-]{8,}\d)(?!\d)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def redact_resume_text(text: str) -> str:
    """Strip direct contact identifiers before resume text leaves the platform."""
    text = _EMAIL_RE.sub("[email removed]", text)
    text = _URL_RE.sub("[link removed]", text)
    return _PHONE_RE.sub("[phone removed]", text)


def require_enabled(settings: Settings) -> None:
    if not settings.ai_interview_enabled:
        raise ConflictError("The AI interview feature is not enabled.")


# --------------------------------------------------------------------------- reads


def get_session(
    db: Session, *, organisation_id: uuid.UUID, session_id: uuid.UUID
) -> AiInterviewSession:
    row = db.get(AiInterviewSession, session_id)
    if row is None or row.organisation_id != organisation_id:
        raise NotFoundError("AI interview not found")
    return row


def list_sessions(
    db: Session, *, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[AiInterviewSession]:
    stmt = (
        select(AiInterviewSession)
        .where(
            AiInterviewSession.organisation_id == organisation_id,
            AiInterviewSession.campaign_id == campaign_id,
        )
        .order_by(AiInterviewSession.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


def _live_session_for(
    db: Session, *, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> AiInterviewSession | None:
    rows = db.execute(
        select(AiInterviewSession).where(
            AiInterviewSession.organisation_id == organisation_id,
            AiInterviewSession.application_id == application_id,
        )
    ).scalars()
    live = [row for row in rows if AiInterviewStatus(row.status) in LIVE_STATUSES]
    # After a retry an application has a finished attempt plus an open one; prefer the open.
    for row in live:
        if row.status != AiInterviewStatus.COMPLETED.value:
            return row
    return live[0] if live else None


# --------------------------------------------------------------------------- inputs


def _role_title(db: Session, application: Application) -> str:
    from app.modules.campaigns.models import Campaign

    campaign = db.get(Campaign, application.campaign_id)
    if campaign is None:
        return "the role"
    return (campaign.position_title or campaign.name or "the role")[:200]


def _jd_payload(db: Session, application: Application, role_title: str) -> list[dict[str, Any]]:
    """The campaign's JD as the agent expects it. Uses the latest APPROVED version, falling
    back to the latest draft so a campaign without an approved JD still works."""
    from app.modules.job_descriptions import service as jd_service

    versions = jd_service.list_versions_for_campaign(
        db, application.organisation_id, application.campaign_id
    )
    if not versions:
        raise ValidationError("This campaign has no job description to plan questions from.")
    approved = [v for v in versions if v.status == "approved"]
    chosen = max(approved or versions, key=lambda v: v.version_number)

    parts: list[str] = []
    if chosen.position_title:
        parts.append(f"Position: {chosen.position_title}")
    if chosen.department:
        parts.append(f"Department: {chosen.department}")
    if chosen.minimum_total_experience_years is not None:
        parts.append(f"Minimum experience (years): {chosen.minimum_total_experience_years:g}")
    if chosen.responsibilities:
        parts.append("Responsibilities:\n- " + "\n- ".join(chosen.responsibilities))
    if chosen.mandatory_skills:
        parts.append("Mandatory skills: " + ", ".join(chosen.mandatory_skills))
    if chosen.desirable_skills:
        parts.append("Desirable skills: " + ", ".join(chosen.desirable_skills))
    text = "\n".join(parts).strip() or f"Position: {role_title}"
    return [
        {
            "jd_id": f"jd-{chosen.id}"[:64],
            "title": (chosen.position_title or role_title)[:200],
            "text": text[:20000],
            "must_have_skills": [s[:80] for s in chosen.mandatory_skills][:30],
        }
    ]


def _resume_text(db: Session, application: Application) -> str:
    from app.modules.extraction.models import ExtractedField

    field = db.execute(
        select(ExtractedField).where(
            ExtractedField.organisation_id == application.organisation_id,
            ExtractedField.application_id == application.id,
            ExtractedField.field_name == "resume_text",
        )
    ).scalars().first()
    text = (field.effective_value or "") if field else ""
    if not text.strip():
        raise ValidationError(
            "No resume text is available for this application, so questions cannot be planned."
        )
    return redact_resume_text(text)[:30000]


# --------------------------------------------------------------------------- draft


def ensure_draft(
    db: Session, *, application: Application, actor_id: uuid.UUID | None = None
) -> AiInterviewSession:
    """Create the PENDING_PLAN draft for an application (idempotent: one live session per
    application). Pure database work, so it is safe to call from the public submit flow."""
    existing = _live_session_for(
        db, organisation_id=application.organisation_id, application_id=application.id
    )
    if existing is not None:
        return existing
    row = AiInterviewSession(
        organisation_id=application.organisation_id,
        campaign_id=application.campaign_id,
        application_id=application.id,
        status=AiInterviewStatus.PENDING_PLAN.value,
        role_title=_role_title(db, application),
        created_by=actor_id,
    )
    db.add(row)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id,
            actor_id=actor_id,
            actor_role=None if actor_id else "system.ai_interview",
            action="ai_interview.drafted",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            new_state_ref=row.status,
        ),
    )
    return row


def draft_after_screening(
    db: Session, *, settings: Settings, application: Application
) -> AiInterviewSession | None:
    """Hook called by screening once a candidate is cleared for interview. Best-effort and
    a no-op when the feature is off; it must never break submission or screening."""
    if not settings.ai_interview_enabled:
        return None
    try:
        # SAVEPOINT: a failure here rolls back only the draft, never the caller's work.
        with db.begin_nested():
            return ensure_draft(db, application=application)
    except Exception:  # noqa: BLE001 - drafting is optional; never break the caller
        return None


# --------------------------------------------------------------------------- plan


def plan_questions(
    db: Session,
    *,
    settings: Settings,
    client: InterviewAgentClient,
    actor: AuthenticatedActor,
    session_id: uuid.UUID,
) -> AiInterviewSession:
    require_enabled(settings)
    row = get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    if row.status not in {
        AiInterviewStatus.PENDING_PLAN.value,
        AiInterviewStatus.QUESTIONS_READY.value,
    }:
        raise ConflictError("Questions can only be planned before the interview is approved.")
    application = db.get(Application, row.application_id)
    if application is None or application.organisation_id != actor.organisation_id:
        raise NotFoundError("Application not found")

    jd = _jd_payload(db, application, row.role_title)
    resume = _resume_text(db, application)
    # Opaque reference: the application id. Never a name or email.
    raw = client.plan_questions(
        interview_id=row.id,
        job_descriptions=jd,
        resume_text=resume,
        candidate_ref=str(application.id),
    )
    try:
        question_set = QuestionSetModel.model_validate(raw)
    except PydanticValidationError as exc:
        raise AgentUnavailableError("The interview agent returned invalid questions.") from exc
    if question_set.interview_id != row.id:
        raise AgentUnavailableError("The interview agent returned questions for another interview.")

    row.question_set = json.loads(question_set.model_dump_json())
    row.question_set_version = question_set.version
    row.generated_by = question_set.generated_by
    row.status = AiInterviewStatus.QUESTIONS_READY.value
    row.updated_by = actor.user_id
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.questions_planned",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            new_state_ref=row.status,
        ),
    )
    return row


# --------------------------------------------------------------------------- approve + link


def _issue_link(row: AiInterviewSession, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    row.link_token_hash = hash_token(token)
    row.link_expires_at = _now() + dt.timedelta(seconds=settings.ai_interview_link_ttl_seconds)
    return token


def link_url_for(settings: Settings, token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/ai-interview/{token}"


def approve_and_issue_link(
    db: Session,
    *,
    settings: Settings,
    actor: AuthenticatedActor,
    session_id: uuid.UUID,
    payload: ApproveRequest,
) -> tuple[AiInterviewSession, str]:
    """A human approves the questions (optionally editing/removing some) and the single-use
    candidate link is issued. The raw token is returned once and never stored."""
    require_enabled(settings)
    row = get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    if row.status != AiInterviewStatus.QUESTIONS_READY.value or not row.question_set:
        raise ConflictError("Questions must be planned and awaiting approval.")

    question_set = dict(row.question_set)
    questions: list[dict[str, Any]] = list(question_set.get("questions", []))
    edited = False
    if payload.questions is not None:
        by_id = {q["id"]: q for q in questions}
        kept: list[dict[str, Any]] = []
        for edit in payload.questions:
            original = by_id.get(edit.id)
            if original is None:
                raise ValidationError(f"Unknown question id: {edit.id}")
            if edit.text != original["text"]:
                edited = True
            kept.append({**original, "text": edit.text})
        if len(kept) != len(questions):
            edited = True
        if not kept:
            raise ValidationError("At least one question must remain.")
        questions = kept
    question_set["questions"] = questions
    if edited:
        question_set["version"] = f"{str(question_set['version'])[:70]}+edited"
    question_set["approved"] = True
    question_set["approved_by"] = str(actor.user_id)

    row.question_set = question_set
    row.question_set_version = str(question_set["version"])
    row.status = AiInterviewStatus.APPROVED.value
    row.approved_by = actor.user_id
    row.approved_at = _now()
    row.updated_by = actor.user_id
    token = _issue_link(row, settings)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.approved_link_issued",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            previous_state_ref=AiInterviewStatus.QUESTIONS_READY.value,
            new_state_ref=row.status,
            reason=(payload.reason or None),
            security_context="candidate_communication_impact",
        ),
    )
    return row, token


def reissue_link(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, session_id: uuid.UUID
) -> tuple[AiInterviewSession, str]:
    require_enabled(settings)
    row = get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    if row.status not in {s.value for s in LINK_ACTIVE_STATUSES} and (
        row.status != AiInterviewStatus.EXPIRED.value
    ):
        raise ConflictError("A new link can only be issued for an approved, unfinished interview.")
    row.status = AiInterviewStatus.APPROVED.value
    row.start_count = 0
    row.updated_by = actor.user_id
    token = _issue_link(row, settings)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.link_reissued",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            new_state_ref=row.status,
            security_context="candidate_communication_impact",
        ),
    )
    return row, token


# Statuses of an attempt that is still open (not finished, not withdrawn).
_OPEN_STATUSES = frozenset(
    {
        AiInterviewStatus.PENDING_PLAN.value,
        AiInterviewStatus.QUESTIONS_READY.value,
        AiInterviewStatus.APPROVED.value,
        AiInterviewStatus.IN_PROGRESS.value,
    }
)


def retry_interview(
    db: Session,
    *,
    settings: Settings,
    actor: AuthenticatedActor,
    session_id: uuid.UUID,
    reason: str,
) -> tuple[AiInterviewSession, str]:
    """Offer another attempt after a finished interview (call dropped, candidate stopped,
    no response, technical error...).

    The finished attempt is NOT changed: its summary, transcript and end reason stay on
    record. A NEW session is created with the same human-approved questions (the acting
    recruiter re-approves them by retrying) and a fresh single-use link. Capped by
    ``ai_interview_max_attempts`` per application, refused while another attempt is still
    open, and audited on both the old and the new attempt.
    """
    require_enabled(settings)
    previous = get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    if previous.status != AiInterviewStatus.COMPLETED.value:
        raise ConflictError("Only a finished interview can be retried.")
    if not previous.question_set or not previous.question_set.get("questions"):
        raise ConflictError("This interview has no approved questions to reuse.")
    if not reason or not reason.strip():
        raise ValidationError("A reason is required to offer another attempt.")

    attempts = list(
        db.execute(
            select(AiInterviewSession).where(
                AiInterviewSession.organisation_id == actor.organisation_id,
                AiInterviewSession.application_id == previous.application_id,
            )
        ).scalars()
    )
    if any(a.status in _OPEN_STATUSES for a in attempts):
        raise ConflictError("Another attempt for this candidate is already open.")
    used = sum(1 for a in attempts if a.status != AiInterviewStatus.REVOKED.value)
    if used >= settings.ai_interview_max_attempts:
        raise ConflictError(
            f"This candidate has used all {settings.ai_interview_max_attempts} AI interview "
            "attempts. Arrange a human interview instead."
        )

    # The agent binds a question set to one interview id and rejects a mismatch, so the copy
    # must carry the NEW attempt's id.
    new_id = uuid.uuid4()
    question_set = dict(previous.question_set)
    question_set["interview_id"] = str(new_id)
    question_set["approved"] = True
    question_set["approved_by"] = str(actor.user_id)
    now = _now()
    row = AiInterviewSession(
        id=new_id,
        organisation_id=previous.organisation_id,
        campaign_id=previous.campaign_id,
        application_id=previous.application_id,
        status=AiInterviewStatus.APPROVED.value,
        role_title=previous.role_title,
        question_set=question_set,
        question_set_version=previous.question_set_version,
        generated_by=previous.generated_by,
        approved_by=actor.user_id,
        approved_at=now,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    token = _issue_link(row, settings)
    db.add(row)
    db.flush()

    clean_reason = reason.strip()[:400]
    ended = previous.end_reason or "unknown"
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.retry_offered",
            entity_type="ai_interview_session",
            entity_id=str(previous.id),
            previous_state_ref=previous.status,
            reason=f"{clean_reason} (new attempt {row.id}; ended: {ended})",
        ),
    )
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.approved_link_issued",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            new_state_ref=row.status,
            reason=f"retry of {previous.id}: {clean_reason}",
            security_context="candidate_communication_impact",
        ),
    )
    return row, token


def revoke(
    db: Session, *, actor: AuthenticatedActor, session_id: uuid.UUID
) -> AiInterviewSession:
    row = get_session(db, organisation_id=actor.organisation_id, session_id=session_id)
    if row.status == AiInterviewStatus.COMPLETED.value:
        raise ConflictError("A completed interview cannot be revoked.")
    previous = row.status
    row.status = AiInterviewStatus.REVOKED.value
    row.link_token_hash = None
    row.updated_by = actor.user_id
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.revoked",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            previous_state_ref=previous,
            new_state_ref=row.status,
        ),
    )
    return row


# --------------------------------------------------------------------------- candidate (public)


def _row_for_token(db: Session, token: str) -> AiInterviewSession:
    """Resolve a link token. Every failure is the same generic 404 so a caller cannot probe
    which tokens exist."""
    invalid = NotFoundError("This interview link is not valid.")
    row = db.execute(
        select(AiInterviewSession).where(AiInterviewSession.link_token_hash == hash_token(token))
    ).scalars().first()
    if row is None:
        raise invalid
    if row.status not in {s.value for s in LINK_ACTIVE_STATUSES}:
        raise invalid
    if row.link_expires_at is None or _aware(row.link_expires_at) < _now():
        raise ConflictError("This interview link has expired. Please contact the recruiter.")
    return row


def public_preview(db: Session, *, settings: Settings, token: str) -> AiInterviewSession:
    require_enabled(settings)
    return _row_for_token(db, token)


def public_start(
    db: Session,
    *,
    settings: Settings,
    client: InterviewAgentClient,
    token: str,
    consent: bool,
    notice_version: str,
) -> tuple[AiInterviewSession, str, str]:
    """Record consent, prime the agent, and return (session, join_token, ws_url)."""
    require_enabled(settings)
    row = _row_for_token(db, token)
    if not consent:
        raise ValidationError("Consent is required to start the interview.")
    if notice_version != NOTICE_VERSION:
        raise ValidationError("The privacy notice has changed. Please reload the page.")
    if row.start_count >= settings.ai_interview_max_starts:
        raise ConflictError("This interview can no longer be restarted. Contact the recruiter.")
    if not row.question_set:
        raise ConflictError("This interview is not ready.")
    # Repair retry attempts created before the question set was re-bound to the new attempt:
    # the questions themselves are the human-approved ones; only the binding id was stale.
    if row.question_set.get("interview_id") != str(row.id):
        row.question_set = {**row.question_set, "interview_id": str(row.id)}

    runtime_session_id = runtime_session_id_for(row.id)
    join_token = client.prepare_session(
        interview_id=row.id,
        question_set=row.question_set,
        role_title=row.role_title,
        consent_notice_version=NOTICE_VERSION,
        runtime_session_id=runtime_session_id,
    )
    ws_url = client.connection_url(runtime_session_id=runtime_session_id)

    row.start_count += 1
    row.status = AiInterviewStatus.IN_PROGRESS.value
    row.consent_notice_version = NOTICE_VERSION
    row.consent_given_at = row.consent_given_at or _now()
    row.started_at = _now()
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=row.organisation_id,
            actor_id=None,
            actor_role="candidate",
            action="ai_interview.started",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            new_state_ref=row.status,
            reason=f"consent {NOTICE_VERSION}",
            security_context="candidate_consent",
        ),
    )
    return row, join_token, ws_url


# --------------------------------------------------------------------------- agent webhook


def verify_webhook_signature(
    *, settings: Settings, body: bytes, timestamp: str | None, signature: str | None
) -> None:
    """HMAC-SHA256 over ``timestamp.body`` with a replay window (matches the agent's
    ``WebhookSink``). Every failure is the same generic 401."""
    secret = settings.ai_interview_webhook_secret
    denied = AuthenticationError("Invalid webhook signature")
    if not secret or not timestamp or not signature:
        raise denied
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise denied from exc
    if abs(time.time() - ts) > settings.ai_interview_webhook_tolerance_seconds:
        raise denied
    expected = hmac.new(
        secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise denied


def ingest_agent_record(
    db: Session, *, settings: Settings, body: bytes, timestamp: str | None, signature: str | None
) -> AiInterviewSession:
    """Store the agent's finished interview. Idempotent by interview id (the agent retries)."""
    require_enabled(settings)
    verify_webhook_signature(
        settings=settings, body=body, timestamp=timestamp, signature=signature
    )
    try:
        record = AgentRecordModel.model_validate_json(body)
    except PydanticValidationError as exc:
        raise ValidationError("Invalid interview record") from exc

    row = db.get(AiInterviewSession, record.summary.interview_id)
    if row is None:
        raise NotFoundError("AI interview not found")
    if row.status == AiInterviewStatus.COMPLETED.value:
        return row  # idempotent retry
    if row.status not in {
        AiInterviewStatus.IN_PROGRESS.value,
        AiInterviewStatus.APPROVED.value,
    }:
        raise ConflictError("This interview is not awaiting a result.")

    parsed = json.loads(body)
    row.summary = parsed["summary"]
    row.transcript = parsed["transcript"]
    row.end_reason = record.summary.end_reason[:32]
    row.completed_at = _now()
    row.status = AiInterviewStatus.COMPLETED.value
    row.link_token_hash = None  # the link is now dead
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=row.organisation_id,
            actor_id=None,
            actor_role="system.ai_interview_agent",
            action="ai_interview.completed",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            new_state_ref=row.status,
            reason=row.end_reason,
        ),
    )
    return row


def record_transcript_view(
    db: Session, *, actor: AuthenticatedActor, row: AiInterviewSession
) -> None:
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id,
            actor_id=actor.user_id,
            action="ai_interview.transcript_viewed",
            entity_type="ai_interview_session",
            entity_id=str(row.id),
            security_context="candidate_pii_access",
        ),
    )
