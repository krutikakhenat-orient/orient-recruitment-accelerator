"""SLA service: compute shortlisting-time status from stored timestamps.

The clock for an application starts when it is submitted. It is "open" while the application
is still waiting for a shortlisting outcome. Waiting on the candidate for more information
pauses the item (it is shown, but not counted as late). Results are computed from stored
timestamps and the stored policy, so they are reproducible and auditable.

Known simplifications (placeholders, see docs/USER_GUIDE.md):
  * Hours are calendar hours; business-hours and holiday calendars are not yet applied.
  * Reminders go to the user who runs the check. Routing along a recruiter -> admin -> HR
    owner chain needs the scheduler and an owner field on campaigns, which are not built yet.
  * "Run check" is a button; an automatic scheduler needs the background-worker setup.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns.models import Campaign
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.notifications import service as notification_service
from app.modules.sla.models import EscalationLevel, SlaEscalation, SlaPolicy
from app.modules.sla.schemas import (
    SlaItemRead,
    SlaPolicyRead,
    SlaRunResult,
    SlaSummaryRead,
)

_S = ApplicationState
OPEN_STATES: frozenset[str] = frozenset(
    {
        _S.SUBMITTED.value,
        _S.DOCUMENTS_PROCESSING.value,
        _S.EXTRACTION_REVIEW.value,
        _S.SCREENED.value,
        _S.MANUAL_REVIEW.value,
        _S.ADDITIONAL_INFO_REQUESTED.value,
    }
)
PAUSED_STATES: frozenset[str] = frozenset({_S.ADDITIONAL_INFO_REQUESTED.value})

DEFAULT_WINDOW_HOURS = 48
DEFAULT_AT_RISK_PERCENT = 75


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _policy_row(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID | None
) -> SlaPolicy | None:
    stmt = select(SlaPolicy).where(
        SlaPolicy.organisation_id == organisation_id,
        SlaPolicy.campaign_id == campaign_id
        if campaign_id is not None
        else SlaPolicy.campaign_id.is_(None),
        SlaPolicy.is_active.is_(True),
    )
    return db.execute(stmt).scalars().first()


def effective_policy(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID | None
) -> SlaPolicyRead:
    row = _policy_row(db, organisation_id, campaign_id) if campaign_id else None
    source = "campaign"
    if row is None:
        row = _policy_row(db, organisation_id, None)
        source = "organisation"
    if row is None:
        return SlaPolicyRead(
            campaign_id=campaign_id, name="Shortlisting target (built-in default)",
            window_hours=DEFAULT_WINDOW_HOURS, at_risk_percent=DEFAULT_AT_RISK_PERCENT,
            source="built_in",
        )
    return SlaPolicyRead(
        campaign_id=row.campaign_id, name=row.name, window_hours=row.window_hours,
        at_risk_percent=row.at_risk_percent, source=source,
    )


def save_policy(
    db: Session,
    *,
    actor: AuthenticatedActor,
    campaign_id: uuid.UUID | None,
    window_hours: int,
    at_risk_percent: int,
) -> SlaPolicyRead:
    row = _policy_row(db, actor.organisation_id, campaign_id)
    if row is None:
        row = SlaPolicy(
            organisation_id=actor.organisation_id, campaign_id=campaign_id,
            created_by=actor.user_id,
        )
        db.add(row)
    row.window_hours = window_hours
    row.at_risk_percent = at_risk_percent
    row.is_active = True
    row.updated_by = actor.user_id
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="sla.policy_saved", entity_type="sla_policy", entity_id=str(row.id),
            new_state_ref=f"{window_hours}h/{at_risk_percent}%",
        ),
    )
    return effective_policy(db, actor.organisation_id, campaign_id)


@dataclass
class _Evaluated:
    application: Application
    status: str
    elapsed: float
    remaining: float


def _classify(app: Application, policy: SlaPolicyRead, now: dt.datetime) -> _Evaluated:
    elapsed = (now - _aware(app.created_at)).total_seconds() / 3600.0
    remaining = policy.window_hours - elapsed
    if app.state in PAUSED_STATES:
        status = "paused"
    elif elapsed >= policy.window_hours:
        status = "overdue"
    elif elapsed >= policy.window_hours * policy.at_risk_percent / 100.0:
        status = "at_risk"
    else:
        status = "on_track"
    return _Evaluated(app, status, round(elapsed, 1), round(remaining, 1))


def evaluate(
    db: Session,
    organisation_id: uuid.UUID,
    campaign_ids: set[uuid.UUID],
    *,
    now: dt.datetime | None = None,
) -> tuple[list[_Evaluated], int]:
    """Return (open items with status, number of already-completed applications)."""
    if not campaign_ids:
        return [], 0
    now = now or dt.datetime.now(dt.UTC)
    stmt = select(Application).where(
        Application.organisation_id == organisation_id,
        Application.campaign_id.in_(campaign_ids),
    )
    apps = list(db.execute(stmt).scalars().all())
    policies: dict[uuid.UUID, SlaPolicyRead] = {}
    items: list[_Evaluated] = []
    completed = 0
    for app in apps:
        if app.state not in OPEN_STATES:
            completed += 1
            continue
        policy = policies.get(app.campaign_id)
        if policy is None:
            policy = effective_policy(db, organisation_id, app.campaign_id)
            policies[app.campaign_id] = policy
        items.append(_classify(app, policy, now))
    return items, completed


def _name(app: Application) -> str:
    value = app.answers.get("full_name") if isinstance(app.answers, dict) else None
    return str(value) if value else "Candidate"


def to_item(ev: _Evaluated) -> SlaItemRead:
    return SlaItemRead(
        application_id=ev.application.id, campaign_id=ev.application.campaign_id,
        candidate_name=_name(ev.application), state=ev.application.state, status=ev.status,
        hours_elapsed=ev.elapsed, hours_remaining=ev.remaining,
        started_at=_aware(ev.application.created_at),
    )


def summary(
    db: Session, organisation_id: uuid.UUID, campaign_ids: set[uuid.UUID],
    campaign_id: uuid.UUID | None,
) -> SlaSummaryRead:
    items, completed = evaluate(db, organisation_id, campaign_ids)
    policy = effective_policy(db, organisation_id, campaign_id)
    counts = {"on_track": 0, "at_risk": 0, "overdue": 0, "paused": 0}
    for ev in items:
        counts[ev.status] += 1
    return SlaSummaryRead(
        window_hours=policy.window_hours, completed=completed,
        note="Hours are counted as calendar hours from the moment an application is submitted.",
        **counts,
    )


def run_check(
    db: Session,
    *,
    settings: Settings,
    actor: AuthenticatedActor,
    campaign_ids: set[uuid.UUID],
) -> SlaRunResult:
    """Record one reminder / overdue notice per application and message the person who ran
    the check (placeholder routing, see module docstring)."""
    items, _ = evaluate(db, actor.organisation_id, campaign_ids)
    by_campaign: dict[uuid.UUID, dict[str, list[Application]]] = {}
    for ev in items:
        if ev.status not in {"at_risk", "overdue"}:
            continue
        level = (
            EscalationLevel.REMINDER.value if ev.status == "at_risk"
            else EscalationLevel.OVERDUE.value
        )
        already = db.execute(
            select(SlaEscalation.id).where(
                SlaEscalation.application_id == ev.application.id,
                SlaEscalation.level == level,
            )
        ).first()
        if already:
            continue
        by_campaign.setdefault(ev.application.campaign_id, {}).setdefault(level, []).append(
            ev.application
        )

    reminders = overdue = 0
    messages: list[str] = []
    for campaign_id, levels in by_campaign.items():
        campaign = db.get(Campaign, campaign_id)
        campaign_name = campaign.name if campaign else "your campaign"
        policy = effective_policy(db, actor.organisation_id, campaign_id)
        for level, apps in levels.items():
            is_reminder = level == EscalationLevel.REMINDER.value
            template = "sla_reminder" if is_reminder else "sla_escalation"
            delivery = notification_service.send_message(
                db, settings=settings, organisation_id=actor.organisation_id,
                triggered_by=actor.user_id, template_key=template, channel="email",
                recipient=actor.email,
                context={
                    "campaign_name": campaign_name, "count": str(len(apps)),
                    "window_hours": str(policy.window_hours),
                },
                campaign_id=campaign_id,
            )
            for app in apps:
                db.add(
                    SlaEscalation(
                        organisation_id=actor.organisation_id, campaign_id=campaign_id,
                        application_id=app.id, level=level, delivery_id=delivery.id,
                        note=f"message status: {delivery.status}",
                    )
                )
            if level == EscalationLevel.REMINDER.value:
                reminders += len(apps)
            else:
                overdue += len(apps)
            messages.append(
                f"{campaign_name}: {len(apps)} {level} notice(s) recorded ({delivery.status})."
            )
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="sla.check_run", entity_type="sla_check",
            reason=f"reminders={reminders}; overdue={overdue}",
        ),
    )
    return SlaRunResult(reminders_recorded=reminders, overdue_recorded=overdue, messages=messages)
