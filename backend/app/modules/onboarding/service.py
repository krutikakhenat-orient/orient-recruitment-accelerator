"""Offers and onboarding service.

Rules enforced here (not in the router):
  * An offer can only be prepared for a SELECTED candidate; only one live offer at a time.
  * An offer is drafted, approved, then issued. Nothing is ever issued automatically.
  * A joining case can only be opened for a SELECTED candidate (data minimisation).
  * Pre-joining, welcome and announcement messages need HR to approve the wording first.
  * A document flag never changes a status by itself; HR resolves each one with a reason.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns.models import Campaign
from app.modules.candidates import service as candidate_service
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.integrations.providers import hrms_provider
from app.modules.notifications import service as notification_service
from app.modules.notifications.models import NotificationDelivery
from app.modules.notifications.schemas import DeliveryRead
from app.modules.onboarding import verification
from app.modules.onboarding.models import (
    ACTIVE_OFFER_STATUSES,
    CaseStatus,
    DocStatus,
    FlagStatus,
    Offer,
    OfferStatus,
    OnboardingCase,
    OnboardingDocument,
    OnboardingDocumentFlag,
)
from app.modules.onboarding.schemas import (
    CaseDetailRead,
    CaseRead,
    DocumentRead,
    FlagRead,
    HrmsPreviewRead,
    OfferRead,
)

DEFAULT_CHECKLIST: tuple[tuple[str, bool], ...] = (
    ("Government ID proof", True),
    ("Address proof", True),
    ("Education certificates", True),
    ("Previous employment documents", True),
    ("Bank account proof", True),
    ("Signed offer letter copy", True),
    ("Passport-size photograph", False),
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _audit(
    db: Session, actor: AuthenticatedActor, action: str, entity_type: str,
    entity_id: uuid.UUID, *, new_state: str | None = None, reason: str | None = None,
) -> None:
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id, action=action,
            entity_type=entity_type, entity_id=str(entity_id), new_state_ref=new_state,
            reason=reason,
        ),
    )


def _role_title(db: Session, campaign_id: uuid.UUID) -> str:
    campaign = db.get(Campaign, campaign_id)
    return campaign.position_title if campaign else "the role"


def _candidate_name(db: Session, organisation_id: uuid.UUID, candidate_id: uuid.UUID) -> str:
    return candidate_service.get_candidate(
        db, organisation_id=organisation_id, candidate_id=candidate_id
    ).full_name


def _delivery_read(delivery: NotificationDelivery | None) -> DeliveryRead | None:
    return DeliveryRead.model_validate(delivery) if delivery else None


# ==================================================================== offers


def get_offer(db: Session, organisation_id: uuid.UUID, offer_id: uuid.UUID) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None or offer.organisation_id != organisation_id:
        raise NotFoundError("Offer not found")
    return offer


def offer_read(
    db: Session, offer: Offer, delivery: NotificationDelivery | None = None
) -> OfferRead:
    app = db.get(Application, offer.application_id)
    name = None
    if app is not None:
        name = _candidate_name(db, offer.organisation_id, app.candidate_id)
    data = OfferRead.model_validate(offer)
    data.candidate_name = name
    data.delivery = _delivery_read(delivery)
    return data


def list_offers(
    db: Session, organisation_id: uuid.UUID, campaign_ids: set[uuid.UUID]
) -> list[Offer]:
    if not campaign_ids:
        return []
    stmt = (
        select(Offer)
        .where(Offer.organisation_id == organisation_id, Offer.campaign_id.in_(campaign_ids))
        .order_by(Offer.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def create_offer(
    db: Session, *, actor: AuthenticatedActor, application: Application,
    notes: str | None, respond_by: dt.date | None,
) -> Offer:
    if application.state != ApplicationState.SELECTED.value:
        raise ValidationError("An offer can only be prepared for a candidate who was selected.")
    existing = db.execute(
        select(Offer.id).where(
            Offer.application_id == application.id, Offer.status.in_(ACTIVE_OFFER_STATUSES)
        )
    ).first()
    if existing:
        raise ConflictError("This candidate already has an offer in progress.")
    offer = Offer(
        organisation_id=actor.organisation_id, application_id=application.id,
        campaign_id=application.campaign_id, status=OfferStatus.DRAFTED.value,
        notes=notes, respond_by=respond_by, created_by=actor.user_id,
    )
    db.add(offer)
    db.flush()
    _audit(db, actor, "offer.drafted", "offer", offer.id, new_state=offer.status)
    return offer


def approve_offer(db: Session, *, actor: AuthenticatedActor, offer: Offer) -> Offer:
    if offer.status != OfferStatus.DRAFTED.value:
        raise ConflictError("Only a drafted offer can be approved.")
    offer.status = OfferStatus.APPROVED.value
    offer.approved_by = actor.user_id
    offer.approved_at = _now()
    db.flush()
    _audit(db, actor, "offer.approved", "offer", offer.id, new_state=offer.status)
    return offer


def _offer_context(db: Session, offer: Offer) -> dict[str, str]:
    return {
        "role": _role_title(db, offer.campaign_id),
        "respond_by": (
            offer.respond_by.isoformat() if offer.respond_by else "the date shared with you"
        ),
    }


def issue_offer(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, offer: Offer,
    application: Application, channel: str,
) -> NotificationDelivery:
    if offer.status != OfferStatus.APPROVED.value:
        raise ConflictError("An offer must be approved before it is issued.")
    delivery = notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=application, template_key="offer_issued", channel=channel,
        context=_offer_context(db, offer),
    )
    offer.status = OfferStatus.ISSUED.value
    offer.issued_at = _now()
    db.flush()
    _audit(db, actor, "offer.issued", "offer", offer.id, new_state=offer.status,
           reason=f"message={delivery.status}")
    return delivery


def remind_offer(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, offer: Offer,
    application: Application, channel: str,
) -> NotificationDelivery:
    if offer.status != OfferStatus.ISSUED.value:
        raise ConflictError("Only an issued offer that has not been answered can be followed up.")
    delivery = notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=application, template_key="offer_followup", channel=channel,
        context=_offer_context(db, offer),
    )
    _audit(db, actor, "offer.followup_sent", "offer", offer.id, reason=f"message={delivery.status}")
    return delivery


def record_offer_response(
    db: Session, *, actor: AuthenticatedActor, offer: Offer, outcome: str
) -> Offer:
    if offer.status != OfferStatus.ISSUED.value:
        raise ConflictError("Only an issued offer can be marked accepted or declined.")
    offer.status = (
        OfferStatus.ACCEPTED.value if outcome == "accepted" else OfferStatus.DECLINED.value
    )
    offer.responded_at = _now()
    db.flush()
    _audit(db, actor, f"offer.{outcome}", "offer", offer.id, new_state=offer.status)
    return offer


def withdraw_offer(db: Session, *, actor: AuthenticatedActor, offer: Offer) -> Offer:
    if offer.status not in ACTIVE_OFFER_STATUSES:
        raise ConflictError("This offer is already closed.")
    offer.status = OfferStatus.WITHDRAWN.value
    db.flush()
    _audit(db, actor, "offer.withdrawn", "offer", offer.id, new_state=offer.status)
    return offer


# ================================================================ onboarding


def get_case(db: Session, organisation_id: uuid.UUID, case_id: uuid.UUID) -> OnboardingCase:
    case = db.get(OnboardingCase, case_id)
    if case is None or case.organisation_id != organisation_id:
        raise NotFoundError("Joining case not found")
    return case


def _documents(db: Session, case_id: uuid.UUID) -> list[OnboardingDocument]:
    stmt = (
        select(OnboardingDocument)
        .where(OnboardingDocument.case_id == case_id)
        .order_by(OnboardingDocument.created_at, OnboardingDocument.name)
    )
    return list(db.execute(stmt).scalars().all())


def _flags(db: Session, case_id: uuid.UUID) -> list[OnboardingDocumentFlag]:
    stmt = (
        select(OnboardingDocumentFlag)
        .where(OnboardingDocumentFlag.case_id == case_id)
        .order_by(OnboardingDocumentFlag.created_at)
    )
    return list(db.execute(stmt).scalars().all())


def case_read(db: Session, case: OnboardingCase) -> CaseRead:
    docs = _documents(db, case.id)
    flags = _flags(db, case.id)
    return CaseRead(
        id=case.id, application_id=case.application_id, campaign_id=case.campaign_id,
        candidate_name=_candidate_name(db, case.organisation_id, case.candidate_id),
        role_title=_role_title(db, case.campaign_id), status=case.status,
        joining_date=case.joining_date, reporting_manager=case.reporting_manager,
        department=case.department, work_location=case.work_location,
        role_expectations=case.role_expectations, content_approved=case.content_approved,
        documents_total=len(docs),
        documents_done=sum(
            1 for d in docs if d.status in {DocStatus.ACCEPTED.value, DocStatus.WAIVED.value}
        ),
        open_flags=sum(1 for f in flags if f.status == FlagStatus.OPEN.value),
        created_at=case.created_at,
    )


def case_detail(db: Session, case: OnboardingCase) -> CaseDetailRead:
    base = case_read(db, case)
    return CaseDetailRead(
        **base.model_dump(),
        documents=[DocumentRead.model_validate(d) for d in _documents(db, case.id)],
        flags=[FlagRead.model_validate(f) for f in _flags(db, case.id)],
        ai_verification_note=verification.AI_VERIFICATION_NOTE,
    )


def list_cases(
    db: Session, organisation_id: uuid.UUID, campaign_ids: set[uuid.UUID]
) -> list[OnboardingCase]:
    if not campaign_ids:
        return []
    stmt = (
        select(OnboardingCase)
        .where(
            OnboardingCase.organisation_id == organisation_id,
            OnboardingCase.campaign_id.in_(campaign_ids),
        )
        .order_by(OnboardingCase.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _recompute_status(db: Session, case: OnboardingCase) -> None:
    if case.status in {CaseStatus.JOINED.value, CaseStatus.WITHDRAWN.value}:
        return
    docs = _documents(db, case.id)
    open_flags = any(f.status == FlagStatus.OPEN.value for f in _flags(db, case.id))
    required = [d for d in docs if d.required]
    done = {DocStatus.ACCEPTED.value, DocStatus.WAIVED.value}
    if required and all(d.status in done for d in required) and not open_flags:
        case.status = CaseStatus.READY_TO_JOIN.value
    elif any(d.status != DocStatus.REQUESTED.value for d in docs):
        case.status = CaseStatus.DOCUMENTS_IN_REVIEW.value
    else:
        case.status = CaseStatus.DOCUMENTS_PENDING.value


def _outstanding(docs: list[OnboardingDocument]) -> list[OnboardingDocument]:
    pending = {DocStatus.REQUESTED.value, DocStatus.CORRECTION_REQUESTED.value}
    return [d for d in docs if d.required and d.status in pending]


def _bullet_list(docs: list[OnboardingDocument]) -> str:
    return "\n".join(f"- {d.name}" for d in docs)


def create_case(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, application: Application,
    joining_date: dt.date | None, reporting_manager: str | None, department: str | None,
    work_location: str | None, role_expectations: str | None,
) -> tuple[OnboardingCase, NotificationDelivery]:
    if application.state != ApplicationState.SELECTED.value:
        raise ValidationError(
            "A joining case can only be opened for a candidate who was selected."
        )
    if db.execute(
        select(OnboardingCase.id).where(OnboardingCase.application_id == application.id)
    ).first():
        raise ConflictError("A joining case already exists for this candidate.")
    case = OnboardingCase(
        organisation_id=actor.organisation_id, application_id=application.id,
        campaign_id=application.campaign_id, candidate_id=application.candidate_id,
        status=CaseStatus.DOCUMENTS_PENDING.value, joining_date=joining_date,
        reporting_manager=reporting_manager, department=department,
        work_location=work_location, role_expectations=role_expectations,
        created_by=actor.user_id,
    )
    db.add(case)
    db.flush()
    for name, required in DEFAULT_CHECKLIST:
        db.add(OnboardingDocument(
            organisation_id=actor.organisation_id, case_id=case.id, name=name, required=required,
            status=DocStatus.REQUESTED.value,
        ))
    db.flush()
    delivery = notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=application, template_key="document_request", channel="email",
        context={
            "role": _role_title(db, application.campaign_id),
            "documents": _bullet_list(_outstanding(_documents(db, case.id))),
        },
        onboarding_case_id=case.id,
    )
    _audit(db, actor, "onboarding.case_opened", "onboarding_case", case.id,
           new_state=case.status, reason=f"message={delivery.status}")
    return case, delivery


def update_case(
    db: Session, *, actor: AuthenticatedActor, case: OnboardingCase, changes: dict[str, object],
) -> OnboardingCase:
    for field in (
        "joining_date", "reporting_manager", "department", "work_location", "role_expectations"
    ):
        if field in changes:
            setattr(case, field, changes[field])
    # Changed wording must be approved again before it is sent.
    case.content_approved = False
    case.content_approved_by = None
    case.updated_by = actor.user_id
    db.flush()
    _audit(db, actor, "onboarding.case_updated", "onboarding_case", case.id)
    return case


def approve_content(db: Session, *, actor: AuthenticatedActor, case: OnboardingCase) -> None:
    if case.joining_date is None:
        raise ValidationError("Enter the joining date before approving the joining messages.")
    case.content_approved = True
    case.content_approved_by = actor.user_id
    db.flush()
    _audit(db, actor, "onboarding.content_approved", "onboarding_case", case.id)


def _document(db: Session, case: OnboardingCase, document_id: uuid.UUID) -> OnboardingDocument:
    doc = db.get(OnboardingDocument, document_id)
    if doc is None or doc.case_id != case.id:
        raise NotFoundError("Document not found on this joining case")
    return doc


def receive_document(
    db: Session, *, actor: AuthenticatedActor, case: OnboardingCase, document_id: uuid.UUID,
    name_on_document: str | None, expiry_date: dt.date | None, note: str | None,
) -> OnboardingDocument:
    doc = _document(db, case, document_id)
    doc.status = DocStatus.SUBMITTED.value
    doc.received_at = _now()
    doc.name_on_document = name_on_document
    doc.expiry_date = expiry_date
    doc.note = note
    db.flush()
    _recompute_status(db, case)
    _audit(db, actor, "onboarding.document_received", "onboarding_document", doc.id,
           new_state=doc.status)
    return doc


def set_document_status(
    db: Session, *, actor: AuthenticatedActor, case: OnboardingCase, document_id: uuid.UUID,
    status: str, note: str | None,
) -> OnboardingDocument:
    doc = _document(db, case, document_id)
    if status == DocStatus.ACCEPTED.value and doc.status == DocStatus.REQUESTED.value:
        raise ConflictError("Mark the document as received before accepting it.")
    doc.status = status
    if note:
        doc.note = note
    db.flush()
    _recompute_status(db, case)
    _audit(db, actor, "onboarding.document_status", "onboarding_document", doc.id,
           new_state=status)
    return doc


def run_verification(
    db: Session, *, actor: AuthenticatedActor, case: OnboardingCase
) -> list[OnboardingDocumentFlag]:
    docs = _documents(db, case.id)
    views = [
        verification.DocumentView(
            id=d.id, name=d.name, required=d.required, status=d.status,
            name_on_document=d.name_on_document, expiry_date=d.expiry_date,
        )
        for d in docs
    ]
    specs = verification.default_verifier().check(
        views,
        candidate_name=_candidate_name(db, case.organisation_id, case.candidate_id),
        joining_date=case.joining_date,
        today=_now().date(),
    )
    existing = _flags(db, case.id)
    resolved_keys = {
        (f.onboarding_document_id, f.kind) for f in existing if f.status != FlagStatus.OPEN.value
    }
    # Refresh the open, rule-based flags; keep anything HR already resolved.
    db.execute(
        delete(OnboardingDocumentFlag).where(
            OnboardingDocumentFlag.case_id == case.id,
            OnboardingDocumentFlag.status == FlagStatus.OPEN.value,
            OnboardingDocumentFlag.source == "rule_based",
        )
    )
    for spec in specs:
        if (spec.document_id, spec.kind) in resolved_keys:
            continue
        db.add(OnboardingDocumentFlag(
            organisation_id=case.organisation_id, case_id=case.id,
            onboarding_document_id=spec.document_id, kind=spec.kind, message=spec.message,
            status=FlagStatus.OPEN.value, source="rule_based",
        ))
    db.flush()
    _recompute_status(db, case)
    _audit(db, actor, "onboarding.verification_run", "onboarding_case", case.id,
           reason=f"flags={len(specs)}")
    return _flags(db, case.id)


def resolve_flag(
    db: Session, *, actor: AuthenticatedActor, case: OnboardingCase, flag_id: uuid.UUID,
    action: str, reason: str,
) -> OnboardingDocumentFlag:
    flag = db.get(OnboardingDocumentFlag, flag_id)
    if flag is None or flag.case_id != case.id:
        raise NotFoundError("Flag not found on this joining case")
    if flag.status != FlagStatus.OPEN.value:
        raise ConflictError("This flag was already resolved.")
    flag.status = action
    flag.resolved_by = actor.user_id
    flag.resolved_at = _now()
    flag.resolution_reason = reason
    if action == FlagStatus.CORRECTION_REQUESTED.value and flag.onboarding_document_id:
        doc = db.get(OnboardingDocument, flag.onboarding_document_id)
        if doc is not None and doc.case_id == case.id:
            doc.status = DocStatus.CORRECTION_REQUESTED.value
    db.flush()
    _recompute_status(db, case)
    _audit(db, actor, "onboarding.flag_resolved", "onboarding_document_flag", flag.id,
           new_state=action, reason=reason)
    return flag


def _application(db: Session, case: OnboardingCase) -> Application:
    app = db.get(Application, case.application_id)
    if app is None:
        raise NotFoundError("Application not found")
    return app


def _joining_context(db: Session, case: OnboardingCase) -> dict[str, str]:
    tbc = "to be confirmed"
    return {
        "role": _role_title(db, case.campaign_id),
        "joining_date": case.joining_date.isoformat() if case.joining_date else tbc,
        "department": case.department or tbc,
        "reporting_manager": case.reporting_manager or tbc,
        "work_location": case.work_location or tbc,
        "role_expectations": case.role_expectations or "Your manager will share this with you.",
    }


def remind_documents(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, case: OnboardingCase,
    channel: str,
) -> NotificationDelivery:
    outstanding = _outstanding(_documents(db, case.id))
    if not outstanding:
        raise ValidationError("Nothing is outstanding: all required documents are in.")
    delivery = notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=_application(db, case), template_key="document_reminder", channel=channel,
        context={"documents": _bullet_list(outstanding)}, onboarding_case_id=case.id,
    )
    _audit(db, actor, "onboarding.documents_reminded", "onboarding_case", case.id,
           reason=f"message={delivery.status}")
    return delivery


def _require_approved(case: OnboardingCase) -> None:
    if not case.content_approved:
        raise ValidationError(
            "HR must approve the joining details before this message can be sent."
        )


def send_prejoining(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, case: OnboardingCase,
    channel: str,
) -> NotificationDelivery:
    _require_approved(case)
    delivery = notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=_application(db, case), template_key="prejoining_info", channel=channel,
        context=_joining_context(db, case), onboarding_case_id=case.id,
    )
    _audit(db, actor, "onboarding.prejoining_sent", "onboarding_case", case.id,
           reason=f"message={delivery.status}")
    return delivery


def send_welcome(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, case: OnboardingCase,
) -> NotificationDelivery:
    _require_approved(case)
    delivery = notification_service.send_to_candidate(
        db, settings=settings, actor=actor, organisation_id=actor.organisation_id,
        application=_application(db, case), template_key="welcome_joiner", channel="email",
        context=_joining_context(db, case), onboarding_case_id=case.id,
    )
    _audit(db, actor, "onboarding.welcome_sent", "onboarding_case", case.id,
           reason=f"message={delivery.status}")
    return delivery


def send_announcement(
    db: Session, *, settings: Settings, actor: AuthenticatedActor, case: OnboardingCase,
    recipients: list[str], joiner_agreed: bool,
) -> list[NotificationDelivery]:
    _require_approved(case)
    if not joiner_agreed:
        raise ValidationError(
            "Confirm that the joiner agreed to be announced (name, role and team only)."
        )
    name = _candidate_name(db, case.organisation_id, case.candidate_id)
    context = {"candidate_name": name, **_joining_context(db, case)}
    deliveries = [
        notification_service.send_message(
            db, settings=settings, organisation_id=actor.organisation_id,
            triggered_by=actor.user_id, template_key="joiner_announcement", channel="email",
            recipient=recipient, context=context, application_id=case.application_id,
            campaign_id=case.campaign_id, onboarding_case_id=case.id,
        )
        for recipient in recipients
    ]
    _audit(db, actor, "onboarding.announcement_sent", "onboarding_case", case.id,
           reason=f"recipients={len(recipients)}")
    return deliveries


def mark_joined(db: Session, *, actor: AuthenticatedActor, case: OnboardingCase) -> None:
    if case.status == CaseStatus.WITHDRAWN.value:
        raise ConflictError("This joining case was withdrawn.")
    case.status = CaseStatus.JOINED.value
    case.joined_at = _now()
    db.flush()
    _audit(db, actor, "onboarding.joined", "onboarding_case", case.id, new_state=case.status)


def hrms_preview(db: Session, case: OnboardingCase) -> HrmsPreviewRead:
    provider = hrms_provider()
    record = provider.build_employee_record(
        {
            "full_name": _candidate_name(db, case.organisation_id, case.candidate_id),
            "designation": _role_title(db, case.campaign_id),
            "department": case.department,
            "reporting_manager": case.reporting_manager,
            "date_of_joining": case.joining_date.isoformat() if case.joining_date else None,
            "work_location": case.work_location,
        }
    )
    result = provider.push_employee_record(record)
    return HrmsPreviewRead(
        provider=provider.name, state=result.state, message=result.message,
        record=result.payload_preview,
    )
