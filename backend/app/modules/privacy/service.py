"""Privacy & retention service (Req 14.1, 14.2; AC-17).

Privacy requests have an auditable lifecycle. Retention policies are configurable per
category and each retention action (notify/restrict/delete/anonymise/legal-hold) is logged
via a RetentionAction row plus an audit event.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.privacy.models import (
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    RecordCategory,
    RetentionAction,
    RetentionActionType,
    RetentionPolicy,
)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def create_privacy_request(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    candidate_id: uuid.UUID,
    request_type: PrivacyRequestType,
    detail: str | None,
    actor_id: uuid.UUID,
) -> PrivacyRequest:
    request = PrivacyRequest(
        organisation_id=organisation_id, candidate_id=candidate_id,
        request_type=request_type.value, status=PrivacyRequestStatus.RECEIVED.value,
        detail=detail, created_by=actor_id,
    )
    db.add(request)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action="privacy_request.received", entity_type="privacy_request",
            entity_id=str(request.id), new_state_ref="received",
            reason=f"type={request_type.value}",
        ),
    )
    return request


def complete_privacy_request(
    db: Session, *, organisation_id: uuid.UUID, request_id: uuid.UUID, actor_id: uuid.UUID,
) -> PrivacyRequest:
    request = db.get(PrivacyRequest, request_id)
    if request is None or request.organisation_id != organisation_id:
        raise NotFoundError("Privacy request not found")
    request.status = PrivacyRequestStatus.COMPLETED.value
    request.handled_by = actor_id
    request.completed_at = _now()
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action="privacy_request.completed", entity_type="privacy_request",
            entity_id=str(request.id), previous_state_ref="received",
            new_state_ref="completed",
        ),
    )
    return request


def set_retention_policy(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    category: RecordCategory,
    retain_days: int,
    action_on_expiry: RetentionActionType,
    actor_id: uuid.UUID,
) -> RetentionPolicy:
    if retain_days < 0:
        raise ValidationError("retain_days must be non-negative")
    policy = RetentionPolicy(
        organisation_id=organisation_id, category=category.value, retain_days=retain_days,
        action_on_expiry=action_on_expiry.value, created_by=actor_id,
    )
    db.add(policy)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action="retention_policy.set", entity_type="retention_policy",
            entity_id=str(policy.id),
            reason=f"category={category.value}; days={retain_days}; "
                   f"action={action_on_expiry.value}",
        ),
    )
    return policy


def record_retention_action(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    category: RecordCategory,
    action_type: RetentionActionType,
    target_entity_type: str,
    target_entity_id: str,
    reason: str,
    actor_id: uuid.UUID | None,
) -> RetentionAction:
    """Record a retention action. Every action is logged (AC-17)."""
    if not reason or not reason.strip():
        raise ValidationError("A reason is required for a retention action")
    action = RetentionAction(
        organisation_id=organisation_id, category=category.value,
        action_type=action_type.value, target_entity_type=target_entity_type,
        target_entity_id=target_entity_id, reason=reason, actor_id=actor_id,
    )
    db.add(action)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor_id,
            action=f"retention.{action_type.value}", entity_type=target_entity_type,
            entity_id=target_entity_id, reason=reason,
        ),
    )
    return action
