"""HR question inbox (Req 7.2-7.5).

The employee chooses to send a question to HR, so the row records who asked. Answers are
shown in-app to the asker; email delivery is an open decision (requirements.md, question 5).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.modules.assistant.guard import scrub_pii
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.documents.storage import ObjectStore
from app.modules.hr_questions.models import HrQuestion, HrQuestionStatus
from app.modules.hr_questions.schemas import HrQuestionInboxRead, HrQuestionRead
from app.modules.identity.models import User
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.policies import service as policy_service
from app.modules.policies.models import PolicyDocument


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _audit(db: Session, actor: AuthenticatedActor, action: str, question: HrQuestion) -> None:
    record_event(db, AuditEventWrite(
        organisation_id=actor.organisation_id, actor_id=actor.user_id, action=action,
        entity_type="hr_question", entity_id=str(question.id), new_state_ref=question.status,
    ))


def escalate(
    db: Session, *, actor: AuthenticatedActor, question: str, contact_preference: str,
    idempotency_key: str | None,
) -> HrQuestion:
    """Create (or, for a repeated idempotency key, return) the HR question."""
    if idempotency_key:
        existing = db.execute(
            select(HrQuestion).where(
                HrQuestion.organisation_id == actor.organisation_id,
                HrQuestion.asked_by == actor.user_id,
                HrQuestion.idempotency_key == idempotency_key,
            )
        ).scalars().first()
        if existing is not None:
            return existing
    row = HrQuestion(
        organisation_id=actor.organisation_id, asked_by=actor.user_id,
        question=question.strip()[:300], contact_preference=contact_preference,
        status=HrQuestionStatus.OPEN.value, idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    _audit(db, actor, "hr_question.created", row)
    return row


def get_question(db: Session, organisation_id: uuid.UUID, question_id: uuid.UUID) -> HrQuestion:
    row = db.get(HrQuestion, question_id)
    if row is None or row.organisation_id != organisation_id:
        raise NotFoundError("Question not found")
    return row


def list_mine(db: Session, actor: AuthenticatedActor) -> list[HrQuestionRead]:
    rows = db.execute(
        select(HrQuestion).where(
            HrQuestion.organisation_id == actor.organisation_id,
            HrQuestion.asked_by == actor.user_id,
        ).order_by(HrQuestion.created_at.desc()).limit(100)
    ).scalars().all()
    return [HrQuestionRead.model_validate(r) for r in rows]


def list_inbox(
    db: Session, organisation_id: uuid.UUID, status: str | None
) -> list[HrQuestionInboxRead]:
    stmt = select(HrQuestion).where(HrQuestion.organisation_id == organisation_id)
    if status:
        stmt = stmt.where(HrQuestion.status == status)
    rows = db.execute(stmt.order_by(HrQuestion.created_at.desc()).limit(200)).scalars().all()
    users = {
        u.id: u for u in db.execute(
            select(User).where(User.id.in_({r.asked_by for r in rows}))
        ).scalars().all()
    } if rows else {}
    out: list[HrQuestionInboxRead] = []
    for r in rows:
        item = HrQuestionInboxRead.model_validate(r)
        user = users.get(r.asked_by)
        item.asked_by_name = user.display_name if user else None
        item.asked_by_email = user.email if user else None
        out.append(item)
    return out


def answer(
    db: Session, *, actor: AuthenticatedActor, question: HrQuestion, text: str
) -> HrQuestion:
    if question.status == HrQuestionStatus.CLOSED.value:
        raise ConflictError("This question is closed.")
    question.answer = text.strip()
    question.answered_by = actor.user_id
    question.answered_at = _now()
    question.status = HrQuestionStatus.ANSWERED.value
    db.flush()
    _audit(db, actor, "hr_question.answered", question)
    return question


def close(db: Session, *, actor: AuthenticatedActor, question: HrQuestion) -> HrQuestion:
    if question.status == HrQuestionStatus.CLOSED.value:
        return question
    question.status = HrQuestionStatus.CLOSED.value
    question.closed_at = _now()
    db.flush()
    _audit(db, actor, "hr_question.closed", question)
    return question


def faq_draft(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, question: HrQuestion
) -> PolicyDocument:
    """Start an FAQ draft from the question. The asker is not named in the FAQ text."""
    text = scrub_pii(question.question)
    body = f"Question: {text}\n\nAnswer: {question.answer or '(to be written by HR)'}"
    return policy_service.create_policy(
        db, actor=actor, store=store, title=text[:255], kind="faq", department=None,
        body=body, effective_date=None,
    )
