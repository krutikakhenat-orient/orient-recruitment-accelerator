"""Policy library service: versions, files, approval and Knowledge Base indexing.

A policy has versions. Revising creates a new draft in the same family; approving it retires
the previous approved version. An approved version is never edited (Req 2.6).

Indexing (Req 2, 3): approving copies the version into the Knowledge Base data source
(``approved/``) and requests a sync. The version it replaces stays searchable until the new
one is Ready. Retiring removes the object and syncs. Draft content is never indexed.

The assistant that answers questions lives in ``app.modules.assistant``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.documents.scanning import MalwareScanner
from app.modules.documents.storage import ObjectStore
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.knowledge_base import service as kb_service
from app.modules.knowledge_base.types import EVERYONE, KnowledgeBase, KnowledgeBaseError
from app.modules.policies import files
from app.modules.policies.audience import actor_audience
from app.modules.policies.models import (
    IndexStatus,
    PolicyAcknowledgement,
    PolicyDocument,
    PolicyStatus,
)
from app.modules.policies.schemas import DuplicateRef, IndexStatusRead, PolicyRead

# Written into FAQ drafts created from a question. A draft that still contains it has no answer
# and must not be approved (it would be published and answer questions with this text).
FAQ_ANSWER_PLACEHOLDER = "(to be written by HR)"


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


def to_read(
    policy: PolicyDocument, *, acknowledged: bool = False, ack_count: int = 0
) -> PolicyRead:
    item = PolicyRead.model_validate(policy)
    item.audience = list(policy.audience or [EVERYONE])
    item.has_file = bool(policy.source_key)
    item.acknowledged = acknowledged
    item.acknowledgement_count = ack_count
    return item


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
    if not manager:
        audience = actor_audience(actor)
        rows = [r for r in rows if audience.allows(r.audience)]
    counts = _ack_counts(db, [r.id for r in rows]) if manager else {}
    mine = _my_acks(db, actor.user_id)
    return [
        to_read(r, acknowledged=mine.get(r.id) == r.version, ack_count=counts.get(r.id, 0))
        for r in rows
    ]


def read_policy(db: Session, actor: AuthenticatedActor, policy: PolicyDocument) -> PolicyRead:
    mine = _my_acks(db, actor.user_id)
    return to_read(policy, acknowledged=mine.get(policy.id) == policy.version,
                   ack_count=_ack_counts(db, [policy.id]).get(policy.id, 0))


# ------------------------------------------------------------------ drafts


def _store_markdown(store: ObjectStore, policy: PolicyDocument) -> None:
    data = files.markdown_for(policy.title, policy.body)
    key = files.draft_key(policy.organisation_id, policy.id, policy.version, ".md")
    store.put(key, data, files.CONTENT_TYPES[".md"])
    policy.source_key = key
    policy.source_content_type = files.CONTENT_TYPES[".md"]
    policy.source_filename = None
    policy.content_hash = hashlib.sha256(data).hexdigest()


def create_policy(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, title: str, kind: str,
    department: str | None, body: str, effective_date: dt.date | None,
    audience: list[str] | None = None, review_due_date: dt.date | None = None,
    publish_with: KnowledgeBase | None = None,
) -> PolicyDocument:
    """Typed-in policy, SOP or FAQ. Stored as a Markdown object so it is indexed like a file.

    With ``publish_with`` (a knowledge base) it is published and sent for syncing at once;
    without it, it stays a draft (``Save as draft``, and FAQ drafts made from a question)."""
    policy = PolicyDocument(
        id=uuid.uuid4(), organisation_id=actor.organisation_id, family_id=uuid.uuid4(),
        title=title.strip(), kind=kind, department=(department or None), body=body, version=1,
        status=PolicyStatus.DRAFT.value, effective_date=effective_date, created_by=actor.user_id,
        audience=audience or None, review_due_date=review_due_date,
        index_status=IndexStatus.NOT_INDEXED.value,
    )
    _store_markdown(store, policy)
    db.add(policy)
    db.flush()
    _audit(db, actor, "policy.drafted", policy)
    if publish_with is not None:
        approve_policy(db, actor=actor, policy=policy, store=store, kb=publish_with)
    return policy


def _duplicates(db: Session, organisation_id: uuid.UUID, content_hash: str) -> list[DuplicateRef]:
    rows = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.organisation_id == organisation_id,
            PolicyDocument.content_hash == content_hash,
        )
    ).scalars().all()
    return [DuplicateRef(id=r.id, title=r.title, version=r.version, status=r.status) for r in rows]


def _accept_file(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, received: files.ReceivedFile,
    policy: PolicyDocument, confirm_duplicate: bool,
) -> None:
    dupes = [d for d in _duplicates(db, actor.organisation_id, received.content_hash)
             if d.id != policy.id]
    if dupes and not confirm_duplicate:
        store.delete(received.quarantine_key)
        raise ConflictError(
            "This file has already been uploaded. Upload it again with 'confirm duplicate' if "
            "you really want a second copy.",
            details={"duplicates": [d.model_dump(mode="json") for d in dupes]},
        )
    key = files.draft_key(actor.organisation_id, policy.id, policy.version, received.extension)
    store.put(key, store.get(received.quarantine_key), received.content_type)
    store.delete(received.quarantine_key)
    policy.source_key = key
    policy.source_filename = received.display_name
    policy.source_content_type = received.content_type
    policy.content_hash = received.content_hash
    policy.body = received.text


def upload_policy(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, scanner: MalwareScanner,
    filename: str, declared_content_type: str, data: bytes, max_bytes: int,
    title: str, kind: str, department: str | None, audience: list[str] | None,
    effective_date: dt.date | None, review_due_date: dt.date | None, confirm_duplicate: bool,
    publish_with: KnowledgeBase | None = None,
) -> PolicyDocument:
    """Validate, scan and store an uploaded file (Req 1). Published and sent for syncing at
    once when ``publish_with`` is given; otherwise kept as a draft."""
    received = files.receive_upload(
        store=store, scanner=scanner, organisation_id=actor.organisation_id, filename=filename,
        declared_content_type=declared_content_type, data=data, max_bytes=max_bytes,
    )
    policy = PolicyDocument(
        id=uuid.uuid4(), organisation_id=actor.organisation_id, family_id=uuid.uuid4(),
        title=title.strip(), kind=kind, department=(department or None), body="", version=1,
        status=PolicyStatus.DRAFT.value, effective_date=effective_date, created_by=actor.user_id,
        audience=audience or None, review_due_date=review_due_date,
        index_status=IndexStatus.NOT_INDEXED.value,
    )
    _accept_file(db, actor=actor, store=store, received=received, policy=policy,
                 confirm_duplicate=confirm_duplicate)
    db.add(policy)
    db.flush()
    _audit(db, actor, "policy.uploaded", policy)
    if publish_with is not None:
        approve_policy(db, actor=actor, policy=policy, store=store, kb=publish_with)
    return policy


def replace_file(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, scanner: MalwareScanner,
    policy: PolicyDocument, filename: str, declared_content_type: str, data: bytes,
    max_bytes: int, confirm_duplicate: bool,
) -> PolicyDocument:
    """Swap the file of a DRAFT (for example a revision of an uploaded policy)."""
    if policy.status != PolicyStatus.DRAFT.value:
        raise ConflictError("Only a draft's file can be replaced. Use 'Revise' first.")
    received = files.receive_upload(
        store=store, scanner=scanner, organisation_id=actor.organisation_id, filename=filename,
        declared_content_type=declared_content_type, data=data, max_bytes=max_bytes,
    )
    old_key = policy.source_key
    _accept_file(db, actor=actor, store=store, received=received, policy=policy,
                 confirm_duplicate=confirm_duplicate)
    if old_key and old_key != policy.source_key and old_key.startswith("draft/"):
        store.delete(old_key)
    policy.updated_by = actor.user_id
    db.flush()
    _audit(db, actor, "policy.file_replaced", policy)
    return policy


def update_policy(
    db: Session, *, actor: AuthenticatedActor, store: ObjectStore, policy: PolicyDocument,
    changes: dict[str, object],
) -> PolicyDocument:
    if policy.status != PolicyStatus.DRAFT.value:
        raise ConflictError(
            "Only a draft can be edited. Use 'Revise' to start a new version of an approved policy."
        )
    markdown = files.CONTENT_TYPES[".md"]
    uploaded = bool(policy.source_content_type) and policy.source_content_type != markdown
    if "body" in changes and uploaded:
        raise ConflictError(
            "The text of an uploaded file cannot be edited here. Replace the file instead."
        )
    for field in ("title", "department", "body", "effective_date", "review_due_date"):
        if field in changes:
            setattr(policy, field, changes[field])
    if "audience" in changes:
        policy.audience = list(changes["audience"] or []) or None  # type: ignore[call-overload]
    if not uploaded and ({"title", "body"} & changes.keys()):
        _store_markdown(store, policy)
    policy.updated_by = actor.user_id
    db.flush()
    _audit(db, actor, "policy.edited", policy)
    return policy


# --------------------------------------------------------------- lifecycle


def _source_bytes(store: ObjectStore, policy: PolicyDocument) -> tuple[bytes, str, str]:
    """The file to index: the stored source, or Markdown built from the text (older rows)."""
    if policy.source_key:
        try:
            return (store.get(policy.source_key), files.extension_of(policy.source_key),
                    policy.source_content_type or files.CONTENT_TYPES[".md"])
        except KeyError:
            pass
    return files.markdown_for(policy.title, policy.body), ".md", files.CONTENT_TYPES[".md"]


def source_loader(store: ObjectStore) -> kb_service.SourceLoader:
    return lambda policy: _source_bytes(store, policy)


def _index(
    db: Session, *, store: ObjectStore, kb: KnowledgeBase, policy: PolicyDocument, reason: str
) -> None:
    data, extension, content_type = _source_bytes(store, policy)
    try:
        policy.approved_key = kb.put_document(
            kb_service.metadata_for(policy), data, extension=extension, content_type=content_type
        )
    except KnowledgeBaseError as exc:
        policy.index_status = IndexStatus.FAILED.value
        policy.index_error = str(exc)[:500]
        db.flush()
        return
    policy.index_status = IndexStatus.INDEXING.value
    policy.index_error = None
    db.flush()
    kb_service.request_sync(db, kb, policy.organisation_id, reason, [policy])


def approve_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument,
    store: ObjectStore, kb: KnowledgeBase,
) -> PolicyDocument:
    if policy.status != PolicyStatus.DRAFT.value:
        raise ConflictError("Only a draft can be approved.")
    if FAQ_ANSWER_PLACEHOLDER in policy.body:
        raise ValidationError(
            "This draft has no answer yet. Click Edit, replace "
            f"'{FAQ_ANSWER_PLACEHOLDER}' with the answer, then approve it."
        )
    previous = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.family_id == policy.family_id,
            PolicyDocument.status == PolicyStatus.APPROVED.value,
        )
    ).scalars().all()
    for old in previous:
        # Retired in the library now; its indexed object stays until this version is Ready.
        old.status = PolicyStatus.RETIRED.value
    policy.status = PolicyStatus.APPROVED.value
    policy.approved_by = actor.user_id
    db.flush()
    _audit(db, actor, "policy.approved", policy)
    _index(db, store=store, kb=kb, policy=policy, reason="approve")
    return policy


def _remove_from_index(kb: KnowledgeBase, policy: PolicyDocument) -> bool:
    if not policy.approved_key:
        return False
    try:
        kb.delete_document(policy.approved_key)
    except KnowledgeBaseError:
        return False  # the answer-time check still hides it; reconcile retries the delete
    policy.approved_key = None
    policy.index_status = IndexStatus.NOT_INDEXED.value
    return True


def retire_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument, kb: KnowledgeBase
) -> PolicyDocument:
    if policy.status != PolicyStatus.APPROVED.value:
        raise ConflictError("Only an approved policy can be retired.")
    policy.status = PolicyStatus.RETIRED.value
    family = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.family_id == policy.family_id,
            PolicyDocument.approved_key.is_not(None),
        )
    ).scalars().all()
    changed = [p for p in family if _remove_from_index(kb, p)]
    db.flush()
    _audit(db, actor, "policy.retired", policy)
    if changed and kb.name != "keyword":
        kb_service.request_sync(db, kb, policy.organisation_id, "retire")
    return policy


def revise_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument, store: ObjectStore
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
        id=uuid.uuid4(), organisation_id=policy.organisation_id, family_id=policy.family_id,
        title=policy.title, kind=policy.kind, department=policy.department, body=policy.body,
        version=int(latest) + 1, status=PolicyStatus.DRAFT.value,
        effective_date=policy.effective_date, created_by=actor.user_id,
        audience=list(policy.audience) if policy.audience else None,
        review_due_date=policy.review_due_date, index_status=IndexStatus.NOT_INDEXED.value,
        source_filename=policy.source_filename, source_content_type=policy.source_content_type,
        content_hash=policy.content_hash,
    )
    data, extension, content_type = _source_bytes(store, policy)
    draft.source_key = files.draft_key(draft.organisation_id, draft.id, draft.version, extension)
    draft.source_content_type = content_type
    store.put(draft.source_key, data, content_type)
    db.add(draft)
    db.flush()
    _audit(db, actor, "policy.revised", draft)
    return draft


def reindex_policy(
    db: Session, *, actor: AuthenticatedActor, policy: PolicyDocument,
    store: ObjectStore, kb: KnowledgeBase,
) -> PolicyDocument:
    if policy.status != PolicyStatus.APPROVED.value:
        raise ConflictError("Only an approved policy can be reindexed.")
    if policy.index_status == IndexStatus.INDEXING.value:
        raise ConflictError("This policy is already being indexed.")
    _audit(db, actor, "policy.reindex_requested", policy)
    _index(db, store=store, kb=kb, policy=policy, reason="reindex")
    return policy


def index_status(db: Session, *, policy: PolicyDocument, kb: KnowledgeBase) -> IndexStatusRead:
    """Refresh running syncs for the organisation, then report this policy's status."""
    kb_service.poll(db, kb, policy.organisation_id)
    db.refresh(policy)
    return IndexStatusRead(
        policy_id=policy.id, status=policy.status, index_status=policy.index_status,
        index_error=policy.index_error, indexed_at=policy.indexed_at,
        ingestion_job_id=policy.ingestion_job_id, backend=kb.name,
    )


def original_file(store: ObjectStore, policy: PolicyDocument) -> tuple[bytes, str, str]:
    """Bytes, content type and download name of the stored source file."""
    if not policy.source_key:
        raise NotFoundError("This policy has no stored file.")
    try:
        data = store.get(policy.source_key)
    except KeyError as exc:
        raise NotFoundError("The stored file could not be found.") from exc
    ext = files.extension_of(policy.source_key)
    name = policy.source_filename or f"policy-v{policy.version}{ext}"
    return data, policy.source_content_type or "application/octet-stream", name


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
