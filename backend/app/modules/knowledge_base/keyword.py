"""Deterministic keyword Knowledge Base (local dev, tests and the Bedrock fallback).

This is the original assistant matcher moved behind the ``KnowledgeBase`` interface. It
searches APPROVED policy text in the database only, so there is nothing to upload or sync:
``put_document`` returns a marker key and every sync is complete at once. No AI is used.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.knowledge_base.types import (
    AudienceFilter,
    Passage,
    PolicyMetadata,
    SyncHandle,
    SyncState,
    SyncStatus,
)
from app.modules.policies.models import PolicyDocument, PolicyStatus

_STOP = frozenset(
    "the and for are you your with that this what how can does about from have has not when "
    "where who why will should would could any our their them they there into than then also "
    "need want know tell please get "
    # Words that appear in almost every HR policy title or question. Matching on them made
    # an unrelated policy "answer" questions like "Is there a pet policy?".
    "policy policies company rule rules guide guides sop faq sample employee employees staff "
    "there".split()
)

# Minimum keyword score for a passage to count as relevant (3 per title word + 1 per body
# word). Unchanged from the original assistant.
KEYWORD_MIN_SCORE = 2.0


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", text.lower()) if t not in _STOP}


def best_sentences(body: str, question_tokens: set[str]) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
    scored = [(len(question_tokens & tokens(s)), i, s) for i, s in enumerate(sentences)]
    top = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1]))[:2]
    if not top:
        return sentences[0][:400] if sentences else ""
    chosen = sorted(top, key=lambda x: x[1])
    return " ".join(s for _, _, s in chosen)[:600]


class KeywordKnowledgeBase:
    name = "keyword"

    def __init__(self, db: Session) -> None:
        self._db = db

    def put_document(
        self, metadata: PolicyMetadata, data: bytes, *, extension: str, content_type: str
    ) -> str:
        return f"keyword://{metadata.policy_id}/v{metadata.version}"

    def delete_document(self, key: str) -> None:
        return None

    def list_documents(self) -> set[str] | None:
        return None

    def start_sync(self) -> SyncHandle:
        return SyncHandle(job_id=None, complete=True)

    def get_sync_status(self, handle: SyncHandle) -> SyncStatus:
        return SyncStatus(state=SyncState.COMPLETE)

    def retrieve(self, query: str, audience: AudienceFilter, top_k: int) -> list[Passage]:
        q_tokens = tokens(query)
        if not q_tokens:
            return []
        rows = self._db.execute(
            select(PolicyDocument).where(
                PolicyDocument.organisation_id == audience.organisation_id,
                PolicyDocument.status == PolicyStatus.APPROVED.value,
            )
        ).scalars().all()
        scored: list[Passage] = []
        for p in rows:
            if not audience.allows(p.audience):
                continue
            score = 3 * len(q_tokens & tokens(p.title)) + len(q_tokens & tokens(p.body))
            if score <= 0:
                continue
            scored.append(Passage(
                policy_id=p.id, version=p.version, title=p.title,
                text=best_sentences(p.body, q_tokens), score=float(score),
            ))
        scored.sort(key=lambda x: (-x.score, x.title))
        return scored[:top_k]
