"""Interview confirmation service.

Flow: HR issues a personal link for an interview invitation -> the candidate opens it (no
login) and confirms, declines or asks for another time -> the assigned interviewers are
told automatically -> HR sees the reply on the invitation.

Capacity rule: a "confirmed" reply is only RECORDED. Slot capacity is still changed solely by
the existing slot-assignment step. A decline or reschedule request releases a held slot.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.modules.applications.models import Application
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns.models import Campaign
from app.modules.candidates import service as candidate_service
from app.modules.identity.models import User
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interview_confirmations.models import InterviewConfirmationLink
from app.modules.interview_confirmations.schemas import (
    LinkStatus,
    PublicPreview,
    PublicResult,
    SuggestedSlot,
)
from app.modules.interviews.models import (
    AttendanceStatus,
    InterviewAssignment,
    InterviewInvitation,
    InterviewSlot,
    InterviewStage,
    InvitationStatus,
)
from app.modules.notifications import service as notification_service
from app.modules.notifications.models import NotificationDelivery

_INVALID = "This link is not valid or has expired. Please contact the HR team."
_LABELS = {
    "confirmed": "confirmed they can attend",
    "declined": "can't attend",
    "reschedule_requested": "asked for a different time",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def as_utc(value: dt.datetime) -> dt.datetime:
    return _aware(value)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_invitation(
    db: Session, organisation_id: uuid.UUID, invitation_id: uuid.UUID
) -> InterviewInvitation:
    invitation = db.get(InterviewInvitation, invitation_id)
    if invitation is None or invitation.organisation_id != organisation_id:
        raise NotFoundError("Invitation not found")
    return invitation


def _application(db: Session, invitation: InterviewInvitation) -> Application:
    app = db.get(Application, invitation.application_id)
    if app is None:
        raise NotFoundError("Application not found")
    return app


def _slot_text(db: Session, invitation: InterviewInvitation) -> tuple[str, str, str]:
    """(when, where, mode) in plain words."""
    slot = db.get(InterviewSlot, invitation.slot_id) if invitation.slot_id else None
    if slot is None:
        return "to be confirmed", "to be confirmed", "to be confirmed"
    return (
        f"{slot.slot_date.isoformat()} at {slot.start_time}",
        slot.location or "to be confirmed",
        slot.mode.replace("_", " "),
    )


def _role(db: Session, campaign_id: uuid.UUID) -> str:
    campaign = db.get(Campaign, campaign_id)
    return campaign.position_title if campaign else "the role"


def _latest_link(db: Session, invitation_id: uuid.UUID) -> InterviewConfirmationLink | None:
    stmt = (
        select(InterviewConfirmationLink)
        .where(InterviewConfirmationLink.invitation_id == invitation_id)
        .order_by(InterviewConfirmationLink.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _link_state(link: InterviewConfirmationLink, now: dt.datetime) -> str:
    if link.used_at is not None:
        return "answered"
    if _aware(link.expires_at) <= now:
        return "expired"
    return "open"


def issue_link(
    db: Session, *, settings: Settings, actor: AuthenticatedActor,
    invitation: InterviewInvitation, send: bool, channel: str,
) -> tuple[str, InterviewConfirmationLink, NotificationDelivery | None]:
    """Create a fresh personal link (older unused links stop working)."""
    # HR booking a slot marks the invitation "confirmed" on HR's side; the candidate can still
    # confirm or decline until the interview has started.
    if invitation.attendance != AttendanceStatus.PENDING.value:
        raise ConflictError("This interview has already started or finished.")
    now = _now()
    for old in db.execute(
        select(InterviewConfirmationLink).where(
            InterviewConfirmationLink.invitation_id == invitation.id,
            InterviewConfirmationLink.used_at.is_(None),
        )
    ).scalars():
        old.expires_at = now
    token = secrets.token_urlsafe(32)
    link = InterviewConfirmationLink(
        organisation_id=actor.organisation_id, invitation_id=invitation.id,
        token_hash=_hash(token),
        expires_at=now + dt.timedelta(hours=settings.confirmation_link_ttl_hours),
        created_by=actor.user_id,
    )
    db.add(link)
    db.flush()
    url = f"{settings.app_base_url.rstrip('/')}/confirm/{token}"
    delivery = None
    if send:
        application = _application(db, invitation)
        delivery = notification_service.send_to_candidate(
            db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
            application=application, template_key="interview_confirm_request",
            channel=channel,
            context={"role": _role(db, invitation.campaign_id), "link": url},
        )
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id,
            action="interview.confirmation_link_issued", entity_type="interview_invitation",
            entity_id=str(invitation.id),
            reason=f"message={delivery.status}" if delivery else "link only",
        ),
    )
    return url, link, delivery


def send_reminder(
    db: Session, *, settings: Settings, actor: AuthenticatedActor,
    invitation: InterviewInvitation, channel: str,
) -> NotificationDelivery:
    when, where, _ = _slot_text(db, invitation)
    return notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=_application(db, invitation), template_key="interview_reminder",
        channel=channel,
        context={"role": _role(db, invitation.campaign_id), "when": when, "where": where},
    )


def link_status(db: Session, invitation: InterviewInvitation) -> LinkStatus:
    link = _latest_link(db, invitation.id)
    if link is None:
        return LinkStatus(
            has_link=False, state="none", response=None, responded_at=None, expires_at=None,
            invitation_status=invitation.status,
            message="No confirmation link has been sent yet.",
        )
    state = _link_state(link, _now())
    messages = {
        "open": "Waiting for the candidate to reply.",
        "expired": "The link expired before the candidate replied. Send a new one.",
        "answered": f"The candidate {_LABELS.get(link.response or '', 'replied')}.",
    }
    return LinkStatus(
        has_link=True, state=state, response=link.response, responded_at=link.used_at,
        expires_at=_aware(link.expires_at), invitation_status=invitation.status,
        message=messages[state],
    )


def suggested_slots(
    db: Session, organisation_id: uuid.UUID, invitation: InterviewInvitation, limit: int = 10
) -> list[SuggestedSlot]:
    """Open slots with spare capacity for this campaign (placeholder for calendar-aware
    suggestions: it uses the slots HR already created, not interviewer calendars)."""
    stmt = (
        select(InterviewSlot, InterviewStage)
        .join(InterviewStage, InterviewSlot.stage_id == InterviewStage.id)
        .where(
            InterviewSlot.organisation_id == organisation_id,
            InterviewStage.campaign_id == invitation.campaign_id,
        )
        .order_by(InterviewSlot.slot_date, InterviewSlot.start_time)
    )
    if invitation.stage_id is not None:
        stmt = stmt.where(InterviewSlot.stage_id == invitation.stage_id)
    today = _now().date()
    rows = [(s, st) for s, st in db.execute(stmt).all() if s.has_capacity]
    upcoming = [r for r in rows if r[0].slot_date >= today]
    chosen = (upcoming or rows)[:limit]
    return [
        SuggestedSlot(
            slot_id=s.id, stage_name=st.name, slot_date=s.slot_date, start_time=s.start_time,
            location=s.location, mode=s.mode, remaining=s.capacity - s.confirmed_count,
        )
        for s, st in chosen
    ]


# ------------------------------------------------------------------ public


def _link_for_token(db: Session, token: str) -> InterviewConfirmationLink:
    stmt = select(InterviewConfirmationLink).where(
        InterviewConfirmationLink.token_hash == _hash(token)
    )
    link = db.execute(stmt).scalars().first()
    if link is None:
        raise NotFoundError(_INVALID)
    return link


def public_preview(db: Session, token: str) -> PublicPreview:
    link = _link_for_token(db, token)
    invitation = db.get(InterviewInvitation, link.invitation_id)
    if invitation is None:
        raise NotFoundError(_INVALID)
    application = _application(db, invitation)
    candidate = candidate_service.get_candidate(
        db, organisation_id=invitation.organisation_id, candidate_id=application.candidate_id
    )
    when, where, mode = _slot_text(db, invitation)
    state = _link_state(link, _now())
    messages = {
        "open": "Please tell us whether you can attend.",
        "answered": "Thank you. We have your reply.",
        "expired": _INVALID,
    }
    # Only the first name is shown: the link is a bearer secret, so keep personal data minimal.
    return PublicPreview(
        state=state, first_name=candidate.full_name.split(" ")[0],
        role_title=_role(db, invitation.campaign_id), when=when, where=where, mode=mode,
        message=messages[state],
    )


def _notify_interviewers(
    db: Session, *, settings: Settings, invitation: InterviewInvitation,
    candidate_name: str, response: str,
) -> int:
    stmt = select(InterviewAssignment).where(
        InterviewAssignment.organisation_id == invitation.organisation_id,
        InterviewAssignment.campaign_id == invitation.campaign_id,
        InterviewAssignment.is_active.is_(True),
    )
    interviewer_ids = {
        a.interviewer_id
        for a in db.execute(stmt).scalars()
        if a.stage_id is None or a.stage_id == invitation.stage_id
    }
    when, _, _ = _slot_text(db, invitation)
    sent = 0
    for user_id in interviewer_ids:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            continue
        notification_service.send_message(
            db, settings=settings, organisation_id=invitation.organisation_id,
            triggered_by=None, template_key="interviewer_confirmation_notice", channel="email",
            recipient=user.email,
            context={
                "candidate_name": candidate_name,
                "role": _role(db, invitation.campaign_id),
                "response": _LABELS.get(response, response),
                "when": when,
            },
            application_id=invitation.application_id, campaign_id=invitation.campaign_id,
        )
        sent += 1
    return sent


def public_respond(
    db: Session, *, settings: Settings, token: str, response: str
) -> PublicResult:
    link = _link_for_token(db, token)
    state = _link_state(link, _now())
    if state == "expired":
        raise NotFoundError(_INVALID)
    if state == "answered":
        raise ConflictError("You have already replied to this invitation. Thank you.")
    invitation = db.get(InterviewInvitation, link.invitation_id)
    if invitation is None:
        raise NotFoundError(_INVALID)
    if invitation.attendance != AttendanceStatus.PENDING.value:
        raise ConflictError("This interview has already taken place. Thank you.")
    application = _application(db, invitation)
    candidate = candidate_service.get_candidate(
        db, organisation_id=invitation.organisation_id, candidate_id=application.candidate_id
    )

    link.used_at = _now()
    link.response = response
    if response in {"declined", "reschedule_requested"}:
        # Release a held slot so someone else can take it.
        if invitation.slot_id is not None:
            slot = db.get(InterviewSlot, invitation.slot_id)
            if slot is not None and invitation.status == InvitationStatus.CONFIRMED.value:
                slot.confirmed_count = max(0, slot.confirmed_count - 1)
            invitation.slot_id = None
        invitation.status = (
            InvitationStatus.DECLINED.value if response == "declined"
            else InvitationStatus.RESCHEDULE_REQUESTED.value
        )
    db.flush()
    notified = _notify_interviewers(
        db, settings=settings, invitation=invitation, candidate_name=candidate.full_name,
        response=response,
    )
    record_event(
        db,
        AuditEventWrite(
            organisation_id=invitation.organisation_id, actor_id=None,
            action="interview.candidate_replied", entity_type="interview_invitation",
            entity_id=str(invitation.id), new_state_ref=response,
            reason=f"interviewers_notified={notified}",
        ),
    )
    texts = {
        "confirmed": "Thank you. Your attendance is confirmed.",
        "declined": "Thank you for letting us know. HR will be in touch.",
        "reschedule_requested": "Thank you. HR will contact you with another time.",
    }
    return PublicResult(response=response, message=texts[response])
