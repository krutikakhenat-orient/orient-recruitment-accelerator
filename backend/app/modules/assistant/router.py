"""HR assistant HTTP router (thin). Asking, feedback and "Send to HR" are open to every
signed-in user; insights and the unanswered list need campaign.approve."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.assistant import service
from app.modules.assistant.composer import (
    AnswerComposer,
    BedrockConverseComposer,
    QuotingComposer,
)
from app.modules.assistant.guard import BedrockGuardrail, NoopGuard, QuestionGuard
from app.modules.assistant.ratelimit import ask_limiter
from app.modules.assistant.schemas import (
    AskRequest,
    AskResponse,
    EscalateRequest,
    FeedbackRead,
    FeedbackRequest,
    InsightsRead,
    UnansweredRead,
)
from app.modules.documents.storage import ObjectStore
from app.modules.hr_questions import service as hr_question_service
from app.modules.hr_questions.schemas import HrQuestionRead
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.knowledge_base.deps import get_knowledge_base, get_policy_file_store
from app.modules.knowledge_base.factory import bedrock_runtime_client
from app.modules.knowledge_base.types import KnowledgeBase
from app.modules.policies import service as policy_service
from app.modules.policies.schemas import PolicyRead

assistant_router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


def get_answer_composer(settings: Settings = Depends(settings_dep)) -> AnswerComposer:
    if not settings.bedrock_kb_active:
        return QuotingComposer()
    assert settings.hr_chatbot_model_id
    return BedrockConverseComposer(
        bedrock_runtime_client(settings), settings.hr_chatbot_model_id,
        guardrail_id=settings.guardrail_id, guardrail_version=settings.guardrail_version,
    )


def get_question_guard(settings: Settings = Depends(settings_dep)) -> QuestionGuard:
    if settings.bedrock_kb_active and settings.guardrail_id:
        return BedrockGuardrail(bedrock_runtime_client(settings), settings.guardrail_id,
                                settings.guardrail_version)
    return NoopGuard()


@assistant_router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    kb: KnowledgeBase = Depends(get_knowledge_base),
    composer: AnswerComposer = Depends(get_answer_composer),
    guard: QuestionGuard = Depends(get_question_guard),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AskResponse:
    """Answer an HR question from approved policies only, with citations. Any signed-in user.
    Rate-limited per user and per client address."""
    limit = settings.chatbot_rate_limit_per_minute
    ask_limiter.hit(f"user:{actor.user_id}", limit)
    if request.client is not None:
        ask_limiter.hit(f"addr:{request.client.host}", limit * 5)
    return service.ask(db, actor=actor, question=payload.question, settings=settings, kb=kb,
                       composer=composer, guard=guard)


@assistant_router.post("/feedback", response_model=FeedbackRead, status_code=201)
def feedback(
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> FeedbackRead:
    """Mark an answer helpful or not. Any signed-in user; stores no user id."""
    return service.record_feedback(db, organisation_id=actor.organisation_id,
                                   query_id=payload.query_id, helpful=payload.helpful,
                                   comment=payload.comment)


@assistant_router.post("/escalate", response_model=HrQuestionRead, status_code=201)
def escalate(
    payload: EscalateRequest,
    idempotency_key: str | None = Header(default=None, max_length=80),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> HrQuestionRead:
    """Send a question to HR. Any signed-in user. Accepts an Idempotency-Key header."""
    row = hr_question_service.escalate(
        db, actor=actor, question=payload.question,
        contact_preference=payload.contact_preference, idempotency_key=idempotency_key,
    )
    return HrQuestionRead.model_validate(row)


@assistant_router.get("/my-questions", response_model=list[HrQuestionRead])
def my_questions(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[HrQuestionRead]:
    """Questions the signed-in person sent to HR, with HR's answers."""
    return hr_question_service.list_mine(db, actor)


@assistant_router.get("/unanswered", response_model=list[UnansweredRead])
def unanswered(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[UnansweredRead]:
    """Questions the assistant could not answer, so HR can add the missing policy.
    Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.list_unanswered(db, actor.organisation_id)


@assistant_router.post("/unanswered/{query_id}/faq-draft", response_model=PolicyRead,
                       status_code=201)
def faq_from_unanswered(
    query_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Start an FAQ draft from an unanswered question. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.faq_draft_from_unanswered(db, actor=actor, store=store, query_id=query_id)
    return policy_service.read_policy(db, actor, policy)


@assistant_router.get("/insights", response_model=InsightsRead)
def insights(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> InsightsRead:
    """Aggregated question statistics, with no per-person view. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.insights(db, organisation_id=actor.organisation_id, days=days)
