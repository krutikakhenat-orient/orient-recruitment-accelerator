"""Policy library and HR assistant service.

The assistant is deterministic and rule-based: it matches words in the question against
APPROVED policy text only, quotes the best-matching sentences, and names its source. When
nothing matches it says so and points the person to HR; it never guesses. An AI model can
later be placed behind the same interface (disabled by default, constrained to the retrieved
text), but nothing here depends on one.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.policies.models import (
    AssistantQueryLog,
    PolicyAcknowledgement,
    PolicyDocument,
    PolicyStatus,
)
from app.modules.policies.schemas import (
    AnswerSource,
    AskResponse,
    PolicyRead,
    UnansweredRead,
)

_STOP = frozenset(
    "the and for are you your with that this what how can does about from have has not when "
    "where who why will should would could any our their them they there into than then also "
    "need want know tell please get".split()
)

ASSISTANT_NOTE = (
    "Answers come only from approved HR policies. If it is not covered, ask HR directly."
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _audit(
    db: Session, actor: AuthenticatedActor, action: str, policy: PolicyDocument,
    *, reason: str | None = None,
) -> None:
    record_event(
        db,
        AuditEventWrite(
            organisation_id=actor.organisation_id, actor_id=actor.user_id, action=action,
            entity_type="policy_document", entity_id=str(policy.id),
            new_state_ref=f"v{policy.version}:{policy.status}", reason=reason,
        ),
    )


def get_policy(db: Session, organisation_id: uuid.UUID, policy_id: uuid.UUID) -> PolicyDocument:
    policy = db.get(PolicyDocument, policy_id)
    if policy is None or policy.organisation_id != organisation_id:
        raise NotFoundError("Policy not found")
    return policy


def _ack_counts(db: Session, policy_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not policy_ids:
        return {}
    rows = db.execute(
        select(PolicyAcknowledgement.policy_id, func.count())
        .where(PolicyAcknowledgement.policy_id.in_(policy_ids))
        .group_by(PolicyAcknowledgement.policy_id)
    ).all()
    return {pid: int(n) for pid, n in rows}


def _my_acks(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(PolicyAcknowledgement.policy_id, PolicyAcknowledgement.policy_version).where(
            PolicyAcknowledgement.user_id == user_id
        )
    ).all()
    return {pid: int(v) for pid, v in rows}


def list_policies(
    db: Session, actor: AuthenticatedActor, *, manager: bool, department: str | None = None
) -> list[PolicyRead]:
    stmt = select(PolicyDocument).where(PolicyDocument.organisation_id == actor.organisation_id)
    if not manager:
        stmt = stmt.where(PolicyDocument.status == PolicyStatus.APPROVED.value)
    if department:
        stmt = stmt.where(
            (PolicyDocument.department.is_(None)) | (PolicyDocument.department == department)
        )
    stmt = stmt.order_by(PolicyDocument.title, PolicyDocument.version.desc())
    rows = list(db.execute(stmt).scalars().all())
    counts = _ack_counts(db, [r.id for r in rows]) if manager else {}
    mine = _my_acks(db, actor.user_id)
    out: list[PolicyRead] = []
    for r in rows:
        item = PolicyRead.model_validate(r)
        item.acknowledged = mine.get(r.id) == r.version
        item.acknowledgement_count = counts.get(r.id, 0)
        out.append(item)
    return out


def create_policy(
    db: Session, *, actor: AuthenticatedActor, title: str, kind: str, department: str | None,
    body: str, effective_date: dt.date | None,
) -> PolicyDocument:
    policy = PolicyDocument(
        organisation_id=actor.organisation_id, family_id=uuid.uuid4(), title=title.strip(),
        kind=kind, department=(department or None), body=body, version=1,
        status=PolicyStatus.DRAFT.value, effective_date=effective_date, created_by=actor.user_id,
    )
    db.add(policy)
    db.flush()
    _audit(db, actor, "policy.drafted", policy)
    return policy


def update_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument, changes: dict[str, object]
) -> PolicyDocument:
    if policy.status != PolicyStatus.DRAFT.value:
        raise ConflictError(
            "Only a draft can be edited. Use 'Revise' to start a new version of an approved policy."
        )
    for field in ("title", "department", "body", "effective_date"):
        if field in changes:
            setattr(policy, field, changes[field])
    policy.updated_by = actor.user_id
    db.flush()
    _audit(db, actor, "policy.edited", policy)
    return policy


def approve_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument
) -> PolicyDocument:
    if policy.status != PolicyStatus.DRAFT.value:
        raise ConflictError("Only a draft can be approved.")
    previous = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.family_id == policy.family_id,
            PolicyDocument.status == PolicyStatus.APPROVED.value,
        )
    ).scalars().all()
    for old in previous:
        old.status = PolicyStatus.RETIRED.value
    policy.status = PolicyStatus.APPROVED.value
    policy.approved_by = actor.user_id
    db.flush()
    _audit(db, actor, "policy.approved", policy)
    return policy


def retire_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument
) -> PolicyDocument:
    if policy.status != PolicyStatus.APPROVED.value:
        raise ConflictError("Only an approved policy can be retired.")
    policy.status = PolicyStatus.RETIRED.value
    db.flush()
    _audit(db, actor, "policy.retired", policy)
    return policy


def revise_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument
) -> PolicyDocument:
    """Start the next version as a draft. The approved version stays live until it is approved."""
    if policy.status != PolicyStatus.APPROVED.value:
        raise ConflictError("Only an approved policy can be revised.")
    latest = db.execute(
        select(func.max(PolicyDocument.version)).where(
            PolicyDocument.family_id == policy.family_id
        )
    ).scalar_one()
    draft_exists = db.execute(
        select(PolicyDocument.id).where(
            PolicyDocument.family_id == policy.family_id,
            PolicyDocument.status == PolicyStatus.DRAFT.value,
        )
    ).first()
    if draft_exists:
        raise ConflictError("A draft revision of this policy already exists.")
    draft = PolicyDocument(
        organisation_id=policy.organisation_id, family_id=policy.family_id, title=policy.title,
        kind=policy.kind, department=policy.department, body=policy.body,
        version=int(latest) + 1, status=PolicyStatus.DRAFT.value,
        effective_date=policy.effective_date, created_by=actor.user_id,
    )
    db.add(draft)
    db.flush()
    _audit(db, actor, "policy.revised", draft)
    return draft


def acknowledge(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument
) -> PolicyAcknowledgement:
    if policy.status != PolicyStatus.APPROVED.value:
        raise ValidationError("Only an approved policy can be acknowledged.")
    existing = db.execute(
        select(PolicyAcknowledgement).where(
            PolicyAcknowledgement.policy_id == policy.id,
            PolicyAcknowledgement.user_id == actor.user_id,
        )
    ).scalars().first()
    if existing is not None:
        return existing
    ack = PolicyAcknowledgement(
        organisation_id=actor.organisation_id, policy_id=policy.id, user_id=actor.user_id,
        policy_version=policy.version, acknowledged_at=_now(),
    )
    db.add(ack)
    db.flush()
    _audit(db, actor, "policy.acknowledged", policy)
    return ack


# ------------------------------------------------------------------ assistant


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", text.lower()) if t not in _STOP}


def _best_sentences(body: str, question_tokens: set[str]) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
    scored = [(len(question_tokens & _tokens(s)), i, s) for i, s in enumerate(sentences)]
    top = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1]))[:2]
    if not top:
        return sentences[0][:400] if sentences else ""
    chosen = sorted(top, key=lambda x: x[1])
    return " ".join(s for _, _, s in chosen)[:600]


def ask(db: Session, organisation_id: uuid.UUID, question: str) -> AskResponse:
    q_tokens = _tokens(question)
    approved = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.organisation_id == organisation_id,
            PolicyDocument.status == PolicyStatus.APPROVED.value,
        )
    ).scalars().all()
    best: tuple[int, PolicyDocument] | None = None
    for p in approved:
        score = 3 * len(q_tokens & _tokens(p.title)) + len(q_tokens & _tokens(p.body))
        if best is None or score > best[0]:
            best = (score, p)

    if best is not None and best[0] >= 2:
        policy = best[1]
        response = AskResponse(
            answered=True,
            answer=_best_sentences(policy.body, q_tokens),
            sources=[AnswerSource(policy_id=policy.id, title=policy.title, version=policy.version)],
            route_to_hr=False,
            note=ASSISTANT_NOTE,
        )
        policy_id: uuid.UUID | None = policy.id
    else:
        policy_id = None
        if "holiday" in question.lower():
            text = (
                "The holiday calendar is not set up in this system yet (placeholder). "
                "Please ask HR for the current list."
            )
        else:
            text = "I could not find this in the approved HR policies. Please ask HR directly."
        response = AskResponse(
            answered=False, answer=text, sources=[], route_to_hr=True, note=ASSISTANT_NOTE
        )

    db.add(
        AssistantQueryLog(
            organisation_id=organisation_id, question=question.strip()[:300],
            answered=response.answered, policy_id=policy_id,
        )
    )
    db.flush()
    return response


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
    return [UnansweredRead(question=r.question, asked_at=r.created_at) for r in rows]
