"""Offers and onboarding HTTP routers (thin).

Permissions (existing ones are reused so current roles keep working without a re-seed):
  offers:       view = candidate.view; draft / follow up = hiring_decision.recommend;
                approve / issue / record reply / withdraw = hiring_decision.approve
  onboarding:   view = candidate.view; documents, checks, reminders = candidate.correct;
                open a case, approve joining wording, send joining messages, mark joined
                = hiring_decision.approve
All of them are also limited to campaigns the user is assigned to.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import (
    require_campaign_access,
    require_campaign_permission,
    require_permission,
)
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.notifications.schemas import DeliveryRead
from app.modules.onboarding import service
from app.modules.onboarding.models import Offer, OnboardingCase
from app.modules.onboarding.schemas import (
    AnnouncementRequest,
    CaseCreate,
    CaseCreated,
    CaseDetailRead,
    CaseRead,
    CaseUpdate,
    DocumentRead,
    DocumentReceive,
    DocumentStatusSet,
    FlagRead,
    FlagResolve,
    HrmsPreviewRead,
    MessagesSent,
    OfferCreate,
    OfferRead,
    OfferRespond,
)

offers_router = APIRouter(prefix="/api/v1/offers", tags=["offers"])
router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

_CHANNEL = Query(default="email", pattern="^(email|whatsapp)$")


def _scope(actor: AuthenticatedActor, campaign_id: uuid.UUID | None) -> set[uuid.UUID]:
    if campaign_id is not None:
        require_campaign_access(actor, campaign_id)
        return {campaign_id}
    return set(actor.assigned_campaign_ids)


# ------------------------------------------------------------------ offers


@offers_router.get("", response_model=list[OfferRead])
def list_offers(
    campaign_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[OfferRead]:
    # Check the permission first: with no assigned campaigns the scope is empty and a
    # per-campaign check would never run.
    require_permission(actor, Permission.CANDIDATE_VIEW)
    scope = _scope(actor, campaign_id)
    for cid in scope:
        require_campaign_permission(actor, Permission.CANDIDATE_VIEW, cid)
    offers = service.list_offers(db, actor.organisation_id, scope)
    return [service.offer_read(db, o) for o in offers]


@offers_router.post("", response_model=OfferRead, status_code=201)
def create_offer(
    payload: OfferCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OfferRead:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(
        actor, Permission.HIRING_DECISION_RECOMMEND, application.campaign_id
    )
    offer = service.create_offer(
        db, actor=actor, application=application, notes=payload.notes,
        respond_by=payload.respond_by,
    )
    return service.offer_read(db, offer)


def _offer_for(
    db: Session, actor: AuthenticatedActor, offer_id: uuid.UUID, permission: Permission
) -> Offer:
    offer = service.get_offer(db, actor.organisation_id, offer_id)
    require_campaign_permission(actor, permission, offer.campaign_id)
    return offer


@offers_router.post("/{offer_id}/approve", response_model=OfferRead)
def approve_offer(
    offer_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OfferRead:
    offer = _offer_for(db, actor, offer_id, Permission.HIRING_DECISION_APPROVE)
    return service.offer_read(db, service.approve_offer(db, actor=actor, offer=offer))


@offers_router.post("/{offer_id}/issue", response_model=OfferRead)
def issue_offer(
    offer_id: uuid.UUID,
    channel: str = _CHANNEL,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OfferRead:
    offer = _offer_for(db, actor, offer_id, Permission.HIRING_DECISION_APPROVE)
    application = application_service.get_application(
        db, actor.organisation_id, offer.application_id
    )
    delivery = service.issue_offer(
        db, settings=settings, actor=actor, offer=offer, application=application, channel=channel
    )
    return service.offer_read(db, offer, delivery)


@offers_router.post("/{offer_id}/remind", response_model=OfferRead)
def remind_offer(
    offer_id: uuid.UUID,
    channel: str = _CHANNEL,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OfferRead:
    offer = _offer_for(db, actor, offer_id, Permission.HIRING_DECISION_RECOMMEND)
    application = application_service.get_application(
        db, actor.organisation_id, offer.application_id
    )
    delivery = service.remind_offer(
        db, settings=settings, actor=actor, offer=offer, application=application, channel=channel
    )
    return service.offer_read(db, offer, delivery)


@offers_router.post("/{offer_id}/respond", response_model=OfferRead)
def respond_offer(
    offer_id: uuid.UUID,
    payload: OfferRespond,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OfferRead:
    """Record the candidate's reply (HR enters it; there is no candidate login yet)."""
    offer = _offer_for(db, actor, offer_id, Permission.HIRING_DECISION_APPROVE)
    return service.offer_read(
        db, service.record_offer_response(db, actor=actor, offer=offer, outcome=payload.outcome)
    )


@offers_router.post("/{offer_id}/withdraw", response_model=OfferRead)
def withdraw_offer(
    offer_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OfferRead:
    offer = _offer_for(db, actor, offer_id, Permission.HIRING_DECISION_APPROVE)
    return service.offer_read(db, service.withdraw_offer(db, actor=actor, offer=offer))


# -------------------------------------------------------------- onboarding


def _case_for(
    db: Session, actor: AuthenticatedActor, case_id: uuid.UUID, permission: Permission
) -> OnboardingCase:
    case = service.get_case(db, actor.organisation_id, case_id)
    require_campaign_permission(actor, permission, case.campaign_id)
    return case


@router.get("/cases", response_model=list[CaseRead])
def list_cases(
    campaign_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[CaseRead]:
    require_permission(actor, Permission.CANDIDATE_VIEW)
    scope = _scope(actor, campaign_id)
    for cid in scope:
        require_campaign_permission(actor, Permission.CANDIDATE_VIEW, cid)
    return [service.case_read(db, c) for c in service.list_cases(db, actor.organisation_id, scope)]


@router.post("/cases", response_model=CaseCreated, status_code=201)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CaseCreated:
    application = application_service.get_application(
        db, actor.organisation_id, payload.application_id
    )
    require_campaign_permission(
        actor, Permission.HIRING_DECISION_APPROVE, application.campaign_id
    )
    case, delivery = service.create_case(
        db, settings=settings, actor=actor, application=application,
        joining_date=payload.joining_date, reporting_manager=payload.reporting_manager,
        department=payload.department, work_location=payload.work_location,
        role_expectations=payload.role_expectations,
    )
    return CaseCreated(
        case=service.case_read(db, case), delivery=DeliveryRead.model_validate(delivery)
    )


@router.get("/cases/{case_id}", response_model=CaseDetailRead)
def get_case(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CaseDetailRead:
    return service.case_detail(db, _case_for(db, actor, case_id, Permission.CANDIDATE_VIEW))


@router.patch("/cases/{case_id}", response_model=CaseDetailRead)
def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CaseDetailRead:
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_CORRECT)
    service.update_case(
        db, actor=actor, case=case, changes=payload.model_dump(exclude_unset=True)
    )
    return service.case_detail(db, case)


@router.post("/cases/{case_id}/approve-content", response_model=CaseDetailRead)
def approve_content(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CaseDetailRead:
    case = _case_for(db, actor, case_id, Permission.HIRING_DECISION_APPROVE)
    service.approve_content(db, actor=actor, case=case)
    return service.case_detail(db, case)


@router.post("/cases/{case_id}/documents/{document_id}/receive", response_model=DocumentRead)
def receive_document(
    case_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentReceive,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DocumentRead:
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_CORRECT)
    doc = service.receive_document(
        db, actor=actor, case=case, document_id=document_id,
        name_on_document=payload.name_on_document, expiry_date=payload.expiry_date,
        note=payload.note,
    )
    return DocumentRead.model_validate(doc)


@router.post("/cases/{case_id}/documents/{document_id}/status", response_model=DocumentRead)
def set_document_status(
    case_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentStatusSet,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DocumentRead:
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_CORRECT)
    doc = service.set_document_status(
        db, actor=actor, case=case, document_id=document_id, status=payload.status,
        note=payload.note,
    )
    return DocumentRead.model_validate(doc)


@router.post("/cases/{case_id}/verify", response_model=list[FlagRead])
def verify_case(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[FlagRead]:
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_CORRECT)
    flags = service.run_verification(db, actor=actor, case=case)
    return [FlagRead.model_validate(f) for f in flags]


@router.post("/cases/{case_id}/flags/{flag_id}/resolve", response_model=FlagRead)
def resolve_flag(
    case_id: uuid.UUID,
    flag_id: uuid.UUID,
    payload: FlagResolve,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> FlagRead:
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_CORRECT)
    flag = service.resolve_flag(
        db, actor=actor, case=case, flag_id=flag_id, action=payload.action, reason=payload.reason
    )
    return FlagRead.model_validate(flag)


@router.post("/cases/{case_id}/remind-documents", response_model=DeliveryRead)
def remind_documents(
    case_id: uuid.UUID,
    channel: str = _CHANNEL,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DeliveryRead:
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_CORRECT)
    return DeliveryRead.model_validate(
        service.remind_documents(db, settings=settings, actor=actor, case=case, channel=channel)
    )


@router.post("/cases/{case_id}/send-prejoining", response_model=DeliveryRead)
def send_prejoining(
    case_id: uuid.UUID,
    channel: str = _CHANNEL,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DeliveryRead:
    case = _case_for(db, actor, case_id, Permission.HIRING_DECISION_APPROVE)
    return DeliveryRead.model_validate(
        service.send_prejoining(db, settings=settings, actor=actor, case=case, channel=channel)
    )


@router.post("/cases/{case_id}/send-welcome", response_model=DeliveryRead)
def send_welcome(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> DeliveryRead:
    case = _case_for(db, actor, case_id, Permission.HIRING_DECISION_APPROVE)
    return DeliveryRead.model_validate(
        service.send_welcome(db, settings=settings, actor=actor, case=case)
    )


@router.post("/cases/{case_id}/send-announcement", response_model=MessagesSent)
def send_announcement(
    case_id: uuid.UUID,
    payload: AnnouncementRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> MessagesSent:
    case = _case_for(db, actor, case_id, Permission.HIRING_DECISION_APPROVE)
    deliveries = service.send_announcement(
        db, settings=settings, actor=actor, case=case,
        recipients=[str(r) for r in payload.recipients], joiner_agreed=payload.joiner_agreed,
    )
    return MessagesSent(deliveries=[DeliveryRead.model_validate(d) for d in deliveries])


@router.post("/cases/{case_id}/mark-joined", response_model=CaseDetailRead)
def mark_joined(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> CaseDetailRead:
    case = _case_for(db, actor, case_id, Permission.HIRING_DECISION_APPROVE)
    service.mark_joined(db, actor=actor, case=case)
    return service.case_detail(db, case)


@router.get("/cases/{case_id}/hrms-preview", response_model=HrmsPreviewRead)
def hrms_preview(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> HrmsPreviewRead:
    """Preview what would be sent to the HR system (ZingHR). Nothing is sent."""
    case = _case_for(db, actor, case_id, Permission.CANDIDATE_VIEW)
    return service.hrms_preview(db, case)
