"""AI voice-interview session ORM model.

One row per candidate application that is offered an automated voice interview run by the
``interview-agent``. The agent is ADVISORY: this table stores its question set, the
candidate's consent, a hashed single-use link token, and the agent's summary/transcript. It
never stores or implies a score, rank or hiring decision, and it never changes the
application's state.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class AiInterviewStatus(str, Enum):
    # Created automatically after screening. No questions yet, nothing sent to the agent.
    PENDING_PLAN = "pending_plan"
    # The agent drafted questions; a human must review and approve them.
    QUESTIONS_READY = "questions_ready"
    # A human approved the questions and the candidate link was issued.
    APPROVED = "approved"
    # The candidate consented and the live session was prepared.
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REVOKED = "revoked"


# States in which the candidate link still works.
LINK_ACTIVE_STATUSES = frozenset({AiInterviewStatus.APPROVED, AiInterviewStatus.IN_PROGRESS})
# States that count as "live" for the one-active-session-per-application rule.
LIVE_STATUSES = frozenset(
    {
        AiInterviewStatus.PENDING_PLAN,
        AiInterviewStatus.QUESTIONS_READY,
        AiInterviewStatus.APPROVED,
        AiInterviewStatus.IN_PROGRESS,
        AiInterviewStatus.COMPLETED,
    }
)


class AiInterviewSession(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "ai_interview_session"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=AiInterviewStatus.PENDING_PLAN.value, index=True
    )
    role_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # The question set drafted by the agent (and optionally edited by a human).
    question_set: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    question_set_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # SHA-256 of the single-use link token. The raw token is shown once and never stored.
    link_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    link_expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    consent_notice_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consent_given_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    start_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Agent output. The transcript is sensitive personal data: it is only returned to actors
    # holding candidate.view_pii, and every read is audited. (Field-level encryption at rest
    # is the storage-layer strategy per security.md; plain JSON here.)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)


class RecordingStatus(str, Enum):
    # The browser is uploading chunks.
    RECORDING = "recording"
    # The browser said it finished (or the upload window closed); ready to play.
    COMPLETE = "complete"
    # Retention period passed, or removed on request: the video data is gone.
    DELETED = "deleted"


class AiInterviewRecording(UUIDPrimaryKey, Timestamped, Base):
    """Video EVIDENCE of one interview attempt, kept for human review only.

    Nothing analyses this video (responsible-ai.md): it is stored, played back to an
    authorised reviewer, and deleted after the retention period. Each start of an interview
    (a candidate may restart a limited number of times) gets its own recording.
    The bytes live in the object store as numbered chunks under ``storage_prefix``; they are
    joined into one file the first time someone plays the finished recording.
    """

    __tablename__ = "ai_interview_recording"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_interview_session.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    attempt_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RecordingStatus.RECORDING.value, index=True
    )
    consent_notice_version: Mapped[str] = mapped_column(String(40), nullable=False)
    consent_given_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # SHA-256 of the upload token the browser holds. Cleared when the upload finishes.
    upload_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    upload_expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    content_type: Mapped[str] = mapped_column(String(64), nullable=False, default="video/webm")
    storage_prefix: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set once the chunks are joined into a single playable file.
    assembled_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_after: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
