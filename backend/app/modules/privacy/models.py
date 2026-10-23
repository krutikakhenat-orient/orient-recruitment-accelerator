"""Privacy & retention ORM models (Req 14.1, 14.2).

PrivacyRequest tracks candidate rights requests (access/export, correction, deletion,
restriction, consent withdrawal). RetentionPolicy configures per-category retention; a
RetentionAction records each notify/restrict/delete/anonymise/legal-hold action taken, so
every retention action is auditable (AC-17).
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class PrivacyRequestType(str, Enum):
    ACCESS_EXPORT = "access_export"
    CORRECTION = "correction"
    DELETION = "deletion"
    PROCESSING_RESTRICTION = "processing_restriction"
    CONSENT_WITHDRAWAL = "consent_withdrawal"


class PrivacyRequestStatus(str, Enum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class RecordCategory(str, Enum):
    CANDIDATE_IDENTITY = "candidate_identity"
    CAMPAIGN_APPLICATION = "campaign_application"
    RESUME = "resume"
    SCREENING_RESULT = "screening_result"
    INTERVIEW_ASSESSMENT = "interview_assessment"
    CANDIDATE_COMMUNICATION = "candidate_communication"
    TALENT_POOL_RECORD = "talent_pool_record"
    AUDIT_EVIDENCE = "audit_evidence"
    SECURITY_LOG = "security_log"


class RetentionActionType(str, Enum):
    NOTIFY_OWNER = "notify_owner"
    RESTRICT_ACCESS = "restrict_access"
    DELETE = "delete"
    ANONYMISE = "anonymise"
    LEGAL_HOLD = "legal_hold"


class PrivacyRequest(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "privacy_request"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PrivacyRequestStatus.RECEIVED.value
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RetentionPolicy(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "retention_policy"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action_on_expiry: Mapped[str] = mapped_column(String(16), nullable=False)
    legal_hold: Mapped[bool] = mapped_column(nullable=False, default=False)


class RetentionAction(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "retention_action"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
