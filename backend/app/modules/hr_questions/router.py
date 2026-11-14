"""HR question inbox HTTP router (thin). Every endpoint requires campaign.approve."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.documents.storage import ObjectStore
from app.modules.hr_questions import service
from app.modules.hr_questions.schemas import AnswerRequest, HrQuestionInboxRead
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.knowledge_base.deps import get_policy_file_store
from app.modules.policies import service as policy_service
from app.modules.policies.schemas import PolicyRead

router = APIRouter(prefix="/api/v1/hr-questions", tags=["hr-questions"])


def _one(db: Session, actor: AuthenticatedActor, question_id: uuid.UUID) -> HrQuestionInboxRead:
    rows = service.list_inbox(db, actor.organisation_id, status=None)
    return next(r for r in rows if r.id == question_id)


@router.get("", response_model=list[HrQuestionInboxRead])
def list_inbox(
    status: str | None = Query(default=None, pattern="^(open|answered|closed)$"),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[HrQuestionInboxRead]:
    """Questions employees sent to HR. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.list_inbox(db, actor.organisation_id, status)


@router.post("/{question_id}/answer", response_model=HrQuestionInboxRead)
def answer(
    question_id: uuid.UUID,
    payload: AnswerRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> HrQuestionInboxRead:
    """Reply to a question (shown to the asker in-app). Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    question = service.get_question(db, actor.organisation_id, question_id)
    service.answer(db, actor=actor, question=question, text=payload.answer)
    return _one(db, actor, question.id)


@router.post("/{question_id}/close", response_model=HrQuestionInboxRead)
def close(
    question_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> HrQuestionInboxRead:
    """Close a question. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    question = service.get_question(db, actor.organisation_id, question_id)
    service.close(db, actor=actor, question=question)
    return _one(db, actor, question.id)


@router.post("/{question_id}/faq-draft", response_model=PolicyRead, status_code=201)
def faq_draft(
    question_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Start an FAQ draft from this question. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    question = service.get_question(db, actor.organisation_id, question_id)
    policy = service.faq_draft(db, actor=actor, store=store, question=question)
    return policy_service.read_policy(db, actor, policy)
