"""Waitlist + controlled re-evaluation service (Req 11.1, 11.2; AC-13).

add_to_waitlist records a waitlist entry tied to the screening run it was based on.
reevaluate performs a NEW screening run only when a permitted trigger applies (new
approved rule/threshold version, new verified info, or an authorised reviewer request).
The original run is always preserved; the service records the initiating user, the reason,
and whether the result changed. New candidate communication requires separate approval
(not performed here).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.applications.models import Application
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.rules import repository as rules_repo
from app.modules.screening import service as screening_service
from app.modules.screening.models import ScreeningRun
from app.modules.waitlist.models import WaitlistRecord, WaitlistStatus


class ReevaluationTrigger(str, Enum):
    RULE_VERSION_CHANGED = "rule_version_changed"
    THRESHOLD_VERSION_CHANGED = "threshold_version_changed"
    NEW_VERIFIED_INFORMATION = "new_verified_information"
    REVIEWER_REQUESTED = "reviewer_requested"


@dataclass
class ReevaluationResult:
    new_run: ScreeningRun
    previous_run_id: uuid.UUID | None
    result_changed: bool


def add_to_waitlist(
    db: Session,
    *,
    actor: AuthenticatedActor,
    application: Application,
    reason: str,
    screening_run_id: uuid.UUID | None,
    eligibility_state: str,
    expires_at: dt.datetime | None = None,
) -> WaitlistRecord:
    if not reason or not reason.strip():
        raise ValidationError("A reason is required to waitlist a candidate")
    record = WaitlistRecord(
        organisation_id=application.organisation_id,
        application_id=application.id,
        campaign_id=application.campaign_id,
        reason=reason,
        screening_run_id=screening_run_id,
        eligibility_state=eligibility_state,
        status=WaitlistStatus.ACTIVE.value,
        expires_at=expires_at,
        created_by=actor.user_id,
    )
    db.add(record)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id, actor_id=actor.user_id,
            action="waitlist.added", entity_type="waitlist_record",
            entity_id=str(record.id), reason=reason,
        ),
    )
    return record


def _latest_run(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> ScreeningRun | None:
    from sqlalchemy import select

    stmt = (
        select(ScreeningRun)
        .where(
            ScreeningRun.organisation_id == organisation_id,
            ScreeningRun.application_id == application_id,
        )
        .order_by(ScreeningRun.started_at.desc(), ScreeningRun.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def reevaluate(
    db: Session,
    *,
    actor: AuthenticatedActor,
    application: Application,
    trigger: ReevaluationTrigger,
    reason: str,
) -> ReevaluationResult:
    """Create a NEW screening run under a permitted trigger (AC-13).

    The original run is preserved. Returns the new run, the previous run id, and whether
    the recommendation changed. New candidate communication must be separately approved.
    """
    if not reason or not reason.strip():
        raise ValidationError("A reason is required to re-evaluate")

    previous = _latest_run(db, actor.organisation_id, application.id)

    rule_version = rules_repo.latest_approved_rule_set_version(
        db, actor.organisation_id, application.campaign_id
    )
    if rule_version is None:
        raise NotFoundError("No approved rule-set version exists for this campaign")
    threshold_version = rules_repo.latest_approved_threshold_version(
        db, actor.organisation_id, application.campaign_id
    )

    result = screening_service.execute_for_application(
        db, organisation_id=actor.organisation_id, application=application,
        rule_set_version=rule_version, threshold_version=threshold_version, actor=actor,
    )
    changed = bool(previous and previous.recommendation != result.run.recommendation)

    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id, actor_id=actor.user_id,
            action="screening.reevaluated", entity_type="screening_run",
            entity_id=str(result.run.id),
            previous_state_ref=str(previous.id) if previous else None,
            new_state_ref=result.run.recommendation,
            reason=f"trigger={trigger.value}; {reason}; changed={changed}",
        ),
    )
    return ReevaluationResult(
        new_run=result.run,
        previous_run_id=previous.id if previous else None,
        result_changed=changed,
    )
