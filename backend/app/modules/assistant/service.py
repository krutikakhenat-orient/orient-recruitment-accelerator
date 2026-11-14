"""HR assistant: answers from approved policy only, with citations (Req 4-8).

Ask flow (design.md 3.2):
 1. Self-service guard, then question guardrail.
 2. Retrieve passages for the asker's audience (+ everyone) from the Knowledge Base. If the
    Bedrock KB fails, the keyword KB answers instead and the reply says so (Req 6.2, 6.3).
 3. Drop passages below the relevance threshold, then re-check every passage against the
    policy row (same organisation, audience allowed, version still searchable). Retrieval
    metadata alone is never trusted (CB-AC-02, CB-AC-04).
 4. Compose an answer from the passages. An answer with no valid citation is discarded.
 5. Log the question (PII-scrubbed) with NO user identifier (Req 8.1, 8.2).

This is information from approved policy only. It never makes or triggers any HR decision.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.modules.assistant.composer import AnswerComposer, ComposerError, QuotingComposer
from app.modules.assistant.guard import (
    GUARDRAIL_REPLY,
    SELF_SERVICE_REPLY,
    QuestionGuard,
    is_self_service,
    scrub_pii,
)
from app.modules.assistant.models import AssistantFeedback
from app.modules.assistant.schemas import (
    AnswerSource,
    AskResponse,
    FeedbackRead,
    InsightsRead,
    QuestionCount,
    ReviewDueRead,
    UnansweredRead,
)
from app.modules.documents.storage import ObjectStore
from app.modules.hr_questions.models import HrQuestion, HrQuestionStatus
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.knowledge_base.keyword import KEYWORD_MIN_SCORE, KeywordKnowledgeBase, tokens
from app.modules.knowledge_base.types import (
    AudienceFilter,
    KnowledgeBase,
    KnowledgeBaseError,
    Passage,
)
from app.modules.policies import service as policy_service
from app.modules.policies.audience import actor_audience
from app.modules.policies.models import (
    AssistantQueryLog,
    IndexStatus,
    PolicyDocument,
    PolicyStatus,
)

ASSISTANT_NOTE = (
    "Answers come only from approved company HR policy. HR decides individual cases; if your "
    "question is not covered, send it to HR."
)
NOT_FOUND_REPLY = "I could not find this in the approved HR policies. Please ask HR directly."
HOLIDAY_REPLY = (
    "The holiday calendar is not set up in this system yet (placeholder). "
    "Please ask HR for the current list."
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _searchable(db: Session, row: PolicyDocument) -> bool:
    """Approved, or a replaced version kept until its successor is Ready (Req 2.4)."""
    if row.status == PolicyStatus.APPROVED.value:
        return True
    if row.status != PolicyStatus.RETIRED.value or not row.approved_key:
        return False
    successor = db.execute(
        select(PolicyDocument.id).where(
            PolicyDocument.family_id == row.family_id,
            PolicyDocument.status == PolicyStatus.APPROVED.value,
            PolicyDocument.version > row.version,
            PolicyDocument.index_status != IndexStatus.READY.value,
        )
    ).first()
    return successor is not None


def verify_passages(
    db: Session, audience: AudienceFilter, passages: list[Passage]
) -> list[Passage]:
    """Keep only passages whose policy row the asker may see right now."""
    if not passages:
        return []
    ids = {p.policy_id for p in passages}
    rows = {
        r.id: r for r in db.execute(
            select(PolicyDocument).where(
                PolicyDocument.id.in_(ids),
                PolicyDocument.organisation_id == audience.organisation_id,
            )
        ).scalars().all()
    }
    kept: list[Passage] = []
    for p in passages:
        row = rows.get(p.policy_id)
        if row is None or row.version != p.version or not audience.allows(row.audience):
            continue
        if not _searchable(db, row):
            continue
        # Title from our own row, never from retrieved metadata.
        kept.append(Passage(policy_id=row.id, version=row.version, title=row.title,
                            text=p.text, score=p.score, page=p.page))
    return kept


def _log(
    db: Session, *, organisation_id: uuid.UUID, question: str, answered: bool,
    policy_id: uuid.UUID | None, via: str | None, retrieved: int | None,
    top_score: float | None, started: float, outcome: str,
) -> AssistantQueryLog:
    entry = AssistantQueryLog(
        organisation_id=organisation_id, question=scrub_pii(question.strip())[:300],
        answered=answered, policy_id=policy_id, answered_via=via, retrieved_count=retrieved,
        top_score=top_score, latency_ms=int((time.perf_counter() - started) * 1000),
        outcome=outcome,
    )
    db.add(entry)
    db.flush()
    return entry


def _retrieve(
    kb: KnowledgeBase, keyword_kb: KeywordKnowledgeBase, question: str,
    audience: AudienceFilter, top_k: int,
) -> tuple[str, list[Passage]]:
    if kb.name != "keyword":
        try:
            return kb.name, kb.retrieve(question, audience, top_k)
        except KnowledgeBaseError:
            pass  # fall back below; the reply carries answered_via=keyword
    return "keyword", keyword_kb.retrieve(question, audience, top_k)


def ask(
    db: Session, *, actor: AuthenticatedActor, question: str, settings: Settings,
    kb: KnowledgeBase, composer: AnswerComposer, guard: QuestionGuard,
) -> AskResponse:
    started = time.perf_counter()
    q = question.strip()
    org = actor.organisation_id

    def reply(text: str, *, outcome: str, via: str | None = None, retrieved: int | None = None,
              top: float | None = None) -> AskResponse:
        entry = _log(db, organisation_id=org, question=q, answered=False, policy_id=None,
                     via=via, retrieved=retrieved, top_score=top, started=started,
                     outcome=outcome)
        return AskResponse(
            answered=False, answer=text, sources=[], route_to_hr=True, note=ASSISTANT_NOTE,
            outcome=outcome, answered_via=via,
            smart_search_unavailable=settings.hr_chatbot_enabled and via == "keyword",
            query_id=entry.id,
        )

    if is_self_service(q):
        return reply(SELF_SERVICE_REPLY, outcome="self_service")
    if not guard.check(q).allowed:
        return reply(GUARDRAIL_REPLY, outcome="guardrail")

    audience = actor_audience(actor)
    keyword_kb = KeywordKnowledgeBase(db)
    via, passages = _retrieve(kb, keyword_kb, q, audience, settings.chatbot_top_k)

    composed = None
    relevant: list[Passage] = []
    for _attempt in range(2):
        min_score = KEYWORD_MIN_SCORE if via == "keyword" else settings.chatbot_min_score
        relevant = verify_passages(db, audience, [p for p in passages if p.score >= min_score])
        if not relevant:
            break
        active = QuotingComposer() if via == "keyword" else composer
        try:
            composed = active.compose(q, relevant)
            break
        except ComposerError:
            if via == "keyword":
                raise
            via, passages = "keyword", keyword_kb.retrieve(q, audience, settings.chatbot_top_k)

    retrieved = len(passages)
    top = max((p.score for p in passages), default=None)
    if composed is not None and composed.blocked:
        return reply(GUARDRAIL_REPLY, outcome="guardrail", via=via, retrieved=retrieved, top=top)
    cited = [n for n in (composed.citations if composed else []) if 1 <= n <= len(relevant)]
    if composed is None or not cited or not composed.text.strip():
        holiday = bool({"holiday", "holidays"} & tokens(q))
        text = HOLIDAY_REPLY if holiday else NOT_FOUND_REPLY
        return reply(text, outcome="not_found", via=via, retrieved=retrieved, top=top)

    sources = [
        AnswerSource(ref=n, policy_id=relevant[n - 1].policy_id, title=relevant[n - 1].title,
                     version=relevant[n - 1].version, page=relevant[n - 1].page,
                     excerpt=relevant[n - 1].text[:300])
        for n in cited
    ]
    entry = _log(db, organisation_id=org, question=q, answered=True,
                 policy_id=sources[0].policy_id, via=via, retrieved=retrieved, top_score=top,
                 started=started, outcome="answered")
    return AskResponse(
        answered=True, answer=composed.text, sources=sources, route_to_hr=False,
        note=ASSISTANT_NOTE, outcome="answered", answered_via=via,
        smart_search_unavailable=settings.hr_chatbot_enabled and via == "keyword",
        query_id=entry.id,
    )


# ---------------------------------------------------------------- feedback


def record_feedback(
    db: Session, *, organisation_id: uuid.UUID, query_id: uuid.UUID, helpful: bool,
    comment: str | None,
) -> FeedbackRead:
    entry = db.get(AssistantQueryLog, query_id)
    if entry is None or entry.organisation_id != organisation_id:
        raise NotFoundError("Answer not found")
    existing = db.execute(
        select(AssistantFeedback.id).where(AssistantFeedback.query_log_id == query_id)
    ).first()
    if existing is not None:
        raise ConflictError("Feedback for this answer was already recorded.")
    feedback = AssistantFeedback(
        organisation_id=organisation_id, query_log_id=query_id, helpful=helpful,
        comment=scrub_pii(comment.strip())[:300] if comment and comment.strip() else None,
    )
    db.add(feedback)
    db.flush()
    return FeedbackRead(id=feedback.id, query_id=query_id, helpful=helpful)


# ---------------------------------------------------------------- HR views


def list_unanswered(
    db: Session, organisation_id: uuid.UUID, limit: int = 50
) -> list[UnansweredRead]:
    rows = db.execute(
        select(AssistantQueryLog)
        .where(
            AssistantQueryLog.organisation_id == organisation_id,
            AssistantQueryLog.answered.is_(False),
        )
        .order_by(AssistantQueryLog.created_at.desc())
        .limit(min(limit, 200))
    ).scalars().all()
    return [UnansweredRead(id=r.id, question=r.question, asked_at=r.created_at) for r in rows]


def faq_draft_from_unanswered(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, query_id: uuid.UUID
) -> PolicyDocument:
    entry = db.get(AssistantQueryLog, query_id)
    if entry is None or entry.organisation_id != actor.organisation_id:
        raise NotFoundError("Question not found")
    return policy_service.create_policy(
        db, actor=actor, store=store, title=entry.question[:255], kind="faq", department=None,
        body=f"Question: {entry.question}\n\nAnswer: (to be written by HR)",
        effective_date=None,
    )


def _top(db: Session, organisation_id: uuid.UUID, since: dt.datetime, *,
         unanswered: bool, limit: int = 10) -> list[QuestionCount]:
    key = func.lower(AssistantQueryLog.question)
    stmt = (
        select(key, func.count())
        .where(AssistantQueryLog.organisation_id == organisation_id,
               AssistantQueryLog.created_at >= since)
        .group_by(key)
        .order_by(func.count().desc(), key)
        .limit(limit)
    )
    if unanswered:
        stmt = stmt.where(AssistantQueryLog.answered.is_(False))
    return [QuestionCount(question=str(q), count=int(n)) for q, n in db.execute(stmt).all()]


def insights(db: Session, *, organisation_id: uuid.UUID, days: int = 30) -> InsightsRead:
    since = _now() - dt.timedelta(days=days)
    base = (AssistantQueryLog.organisation_id == organisation_id,
            AssistantQueryLog.created_at >= since)
    total = db.execute(select(func.count()).where(*base)).scalar_one()
    answered = db.execute(
        select(func.count()).where(*base, AssistantQueryLog.answered.is_(True))
    ).scalar_one()
    outcomes: dict[str | None, int] = {
        outcome: int(n) for outcome, n in db.execute(
            select(AssistantQueryLog.outcome, func.count()).where(*base)
            .group_by(AssistantQueryLog.outcome)
        ).all()
    }
    by_backend = {
        str(via): int(n) for via, n in db.execute(
            select(AssistantQueryLog.answered_via, func.count())
            .where(*base, AssistantQueryLog.answered_via.is_not(None))
            .group_by(AssistantQueryLog.answered_via)
        ).all()
    }
    fb: dict[bool, int] = {
        bool(flag): int(n) for flag, n in db.execute(
            select(AssistantFeedback.helpful, func.count())
            .where(AssistantFeedback.organisation_id == organisation_id,
                   AssistantFeedback.created_at >= since)
            .group_by(AssistantFeedback.helpful)
        ).all()
    }
    helpful, not_helpful = int(fb.get(True, 0)), int(fb.get(False, 0))
    open_questions = db.execute(
        select(func.count()).where(HrQuestion.organisation_id == organisation_id,
                                   HrQuestion.status == HrQuestionStatus.OPEN.value)
    ).scalar_one()
    due_rows = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.organisation_id == organisation_id,
            PolicyDocument.status == PolicyStatus.APPROVED.value,
            PolicyDocument.review_due_date.is_not(None),
            PolicyDocument.review_due_date <= _now().date(),
        ).order_by(PolicyDocument.review_due_date)
    ).scalars().all()
    rated = helpful + not_helpful
    return InsightsRead(
        period_days=days, total_questions=int(total), answered=int(answered),
        not_found=int(outcomes.get("not_found", 0)),
        self_service=int(outcomes.get("self_service", 0)),
        guardrail_blocked=int(outcomes.get("guardrail", 0)), by_backend=by_backend,
        helpful=helpful, not_helpful=not_helpful,
        not_helpful_rate=round(not_helpful / rated, 3) if rated else None,
        top_questions=_top(db, organisation_id, since, unanswered=False),
        top_unanswered=_top(db, organisation_id, since, unanswered=True),
        open_hr_questions=int(open_questions),
        review_due=[ReviewDueRead(policy_id=r.id, title=r.title, version=r.version,
                                  review_due_date=r.review_due_date)  # type: ignore[arg-type]
                    for r in due_rows],
    )
