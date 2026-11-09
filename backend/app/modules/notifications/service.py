"""Notification service: render a template, hand it to a provider, record the outcome.

The recorded status is honest (see models.DeliveryStatus). Audit events carry no recipient
address or message body (PII-safe, steering: security.md).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ValidationError
from app.modules.applications.models import Application
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.candidates import service as candidate_service
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.notifications import providers, templates
from app.modules.notifications.models import (
    Channel,
    NotificationDelivery,
    NotificationTemplate,
)
from app.modules.notifications.schemas import (
    NotificationStatusRead,
    TemplateRead,
)


def status(settings: Settings) -> NotificationStatusRead:
    return NotificationStatusRead(
        email=providers.channel_state(Channel.EMAIL.value, settings),  # type: ignore[arg-type]
        whatsapp=providers.channel_state(Channel.WHATSAPP.value, settings),  # type: ignore[arg-type]
    )


def _active_override(
    db: Session, organisation_id: uuid.UUID, key: str
) -> NotificationTemplate | None:
    stmt = (
        select(NotificationTemplate)
        .where(
            NotificationTemplate.organisation_id == organisation_id,
            NotificationTemplate.key == key,
            NotificationTemplate.is_active.is_(True),
        )
        .order_by(NotificationTemplate.version.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _template_read(
    built: templates.BuiltInTemplate, override: NotificationTemplate | None
) -> TemplateRead:
    return TemplateRead(
        key=built.key,
        label=built.label,
        audience=built.audience,
        description=built.description,
        subject=override.subject if override else built.subject,
        body=override.body if override else built.body,
        version=override.version if override else 0,
        placeholders=list(built.placeholders),
        is_built_in=override is None,
    )


def list_templates(db: Session, organisation_id: uuid.UUID) -> list[TemplateRead]:
    return [
        _template_read(t, _active_override(db, organisation_id, t.key))
        for t in templates.BUILT_IN_TEMPLATES
    ]


def save_template(
    db: Session, *, actor: AuthenticatedActor, key: str, subject: str, body: str
) -> TemplateRead:
    built = templates.built_in(key)
    unknown = (templates.placeholders_in(subject) | templates.placeholders_in(body)) - set(
        built.placeholders
    )
    if unknown:
        raise ValidationError(
            "Unknown placeholder(s): " + ", ".join(sorted(unknown))
            + ". Allowed: " + ", ".join(built.placeholders)
        )
    current = _active_override(db, actor.organisation_id, key)
    next_version = (current.version if current else 0) + 1
    if current:
        current.is_active = False
    row = NotificationTemplate(
        organisation_id=actor.organisation_id,
        key=key,
        version=next_version,
        subject=templates.single_line(subject),
        body=body,
        is_active=True,
        created_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="notification.template_saved", entity_type="notification_template",
            entity_id=str(row.id), new_state_ref=f"{key}@v{next_version}",
        ),
    )
    return _template_read(built, row)


def send_message(
    db: Session,
    *,
    settings: Settings,
    organisation_id: uuid.UUID,
    triggered_by: uuid.UUID | None,
    template_key: str,
    channel: str,
    recipient: str,
    context: dict[str, str],
    application_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    onboarding_case_id: uuid.UUID | None = None,
) -> NotificationDelivery:
    """Render + deliver one message and record the honest outcome."""
    if not recipient or not recipient.strip():
        raise ValidationError("There is no address to send this message to.")
    built = templates.built_in(template_key)
    override = _active_override(db, organisation_id, template_key)
    subject_tpl = override.subject if override else built.subject
    body_tpl = override.body if override else built.body

    subject = templates.single_line(templates.render(subject_tpl, built.placeholders, context))
    body = templates.render(body_tpl, built.placeholders, context)

    provider = providers.provider_for(channel, settings)
    result = provider.send(to=recipient, subject=subject, body=body)

    delivery = NotificationDelivery(
        organisation_id=organisation_id,
        campaign_id=campaign_id,
        application_id=application_id,
        onboarding_case_id=onboarding_case_id,
        template_key=template_key,
        template_version=override.version if override else 0,
        channel=channel,
        recipient=recipient.strip(),
        subject=subject if channel == Channel.EMAIL.value else None,
        body=body,
        status=result.status,
        provider_response_id=result.provider_response_id,
        failure_reason=result.failure_reason,
        manual_link=providers.manual_link(channel, recipient.strip(), subject, body),
        triggered_by=triggered_by,
    )
    db.add(delivery)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=triggered_by,
            action="notification.recorded", entity_type="notification_delivery",
            entity_id=str(delivery.id), new_state_ref=result.status,
            reason=f"template={template_key}; channel={channel}",
        ),
    )
    return delivery


def send_to_candidate(
    db: Session,
    *,
    settings: Settings,
    actor: AuthenticatedActor | None,
    organisation_id: uuid.UUID,
    application: Application,
    template_key: str,
    channel: str,
    context: dict[str, str],
    onboarding_case_id: uuid.UUID | None = None,
) -> NotificationDelivery:
    """Send to the candidate behind an application (email or mobile, per channel)."""
    candidate = candidate_service.get_candidate(
        db, organisation_id=organisation_id, candidate_id=application.candidate_id
    )
    recipient = candidate.email if channel == Channel.EMAIL.value else (candidate.mobile or "")
    if channel == Channel.WHATSAPP.value and not recipient:
        raise ValidationError("This candidate has no mobile number on record for WhatsApp.")
    base_context = {"candidate_name": candidate.full_name}
    base_context.update(context)
    return send_message(
        db,
        settings=settings,
        organisation_id=organisation_id,
        triggered_by=actor.user_id if actor else None,
        template_key=template_key,
        channel=channel,
        recipient=recipient,
        context=base_context,
        application_id=application.id,
        campaign_id=application.campaign_id,
        onboarding_case_id=onboarding_case_id,
    )


def list_deliveries(
    db: Session,
    organisation_id: uuid.UUID,
    *,
    application_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    onboarding_case_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[NotificationDelivery]:
    stmt = select(NotificationDelivery).where(
        NotificationDelivery.organisation_id == organisation_id
    )
    if application_id:
        stmt = stmt.where(NotificationDelivery.application_id == application_id)
    if campaign_id:
        stmt = stmt.where(NotificationDelivery.campaign_id == campaign_id)
    if onboarding_case_id:
        stmt = stmt.where(NotificationDelivery.onboarding_case_id == onboarding_case_id)
    stmt = stmt.order_by(NotificationDelivery.created_at.desc()).limit(min(limit, 200))
    return list(db.execute(stmt).scalars().all())
