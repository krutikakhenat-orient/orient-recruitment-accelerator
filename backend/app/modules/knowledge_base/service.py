"""Sync coalescing, index-status polling and nightly reconcile (Req 3.2-3.5).

Rules:
- At most one ``running`` and one ``queued`` sync request per organisation. A change made
  while a job runs joins the queued request and is picked up by the next job.
- A policy waiting for indexing points at the request that will index it
  (``kb_sync_request_id``). When that request finishes, the policy becomes Ready or Index
  failed. A failed sync keeps the previous Ready version in use (its object is untouched).
- After a revision is Ready, objects of the versions it replaced are removed and a cleanup
  sync runs (Req 2.4).
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.knowledge_base.models import KbSyncRequest, SyncState
from app.modules.knowledge_base.types import (
    KnowledgeBase,
    KnowledgeBaseBusyError,
    KnowledgeBaseError,
    PolicyMetadata,
    SyncHandle,
)
from app.modules.knowledge_base.types import SyncState as JobState
from app.modules.policies.models import IndexStatus, PolicyDocument, PolicyStatus

log = logging.getLogger(__name__)

# Returns (file bytes, extension, content type) for an approved policy's source.
SourceLoader = Callable[[PolicyDocument], tuple[bytes, str, str]]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _audit(db: Session, organisation_id: uuid.UUID, action: str, policy: PolicyDocument,
           reason: str | None = None) -> None:
    record_event(db, AuditEventWrite(
        organisation_id=organisation_id, actor_id=None, actor_role="system", action=action,
        entity_type="policy_document", entity_id=str(policy.id),
        new_state_ref=f"v{policy.version}:{policy.index_status}", reason=reason,
    ))


def _active(db: Session, organisation_id: uuid.UUID, state: SyncState) -> KbSyncRequest | None:
    return db.execute(
        select(KbSyncRequest).where(
            KbSyncRequest.organisation_id == organisation_id,
            KbSyncRequest.status == state.value,
        ).order_by(KbSyncRequest.created_at)
    ).scalars().first()


def _start(db: Session, kb: KnowledgeBase, request: KbSyncRequest) -> None:
    try:
        handle = kb.start_sync()
    except KnowledgeBaseBusyError:
        request.status = SyncState.QUEUED.value  # try again on the next poll
        return
    except KnowledgeBaseError as exc:
        request.status = SyncState.FAILED.value
        request.error = str(exc)[:500]
        request.finished_at = _now()
        db.flush()
        _settle(db, kb, request)
        return
    request.ingestion_job_id = handle.job_id
    request.started_at = _now()
    if handle.complete:
        request.status = SyncState.COMPLETE.value
        request.finished_at = _now()
        db.flush()
        _settle(db, kb, request)
    else:
        request.status = SyncState.RUNNING.value
        db.flush()


def request_sync(
    db: Session, kb: KnowledgeBase, organisation_id: uuid.UUID, reason: str,
    policies: list[PolicyDocument] | None = None,
) -> KbSyncRequest:
    """Ask for a sync, merging into the queued request when a job is already running."""
    queued = _active(db, organisation_id, SyncState.QUEUED)
    running = _active(db, organisation_id, SyncState.RUNNING)
    if running is not None or queued is not None:
        request = queued or KbSyncRequest(
            organisation_id=organisation_id, reason=reason, status=SyncState.QUEUED.value
        )
        db.add(request)
        db.flush()
        for policy in policies or []:
            policy.kb_sync_request_id = request.id
        db.flush()
        if running is None:
            _start(db, kb, request)  # a stale queue with nothing running: start it now
        return request

    request = KbSyncRequest(
        organisation_id=organisation_id, reason=reason, status=SyncState.QUEUED.value
    )
    db.add(request)
    db.flush()
    for policy in policies or []:
        policy.kb_sync_request_id = request.id
    db.flush()
    _start(db, kb, request)
    return request


def _settle(db: Session, kb: KnowledgeBase, request: KbSyncRequest) -> None:
    """Apply a finished request to the policies it was indexing."""
    waiting = db.execute(
        select(PolicyDocument).where(
            PolicyDocument.kb_sync_request_id == request.id,
            PolicyDocument.index_status == IndexStatus.INDEXING.value,
        )
    ).scalars().all()
    ready: list[PolicyDocument] = []
    for policy in waiting:
        # A COMPLETE job that still reports failed documents carries an error; Bedrock does
        # not say which file failed, so every policy in the batch is offered a Reindex.
        if request.status == SyncState.COMPLETE.value and request.error is None:
            policy.index_status = IndexStatus.READY.value
            policy.index_error = None
            policy.indexed_at = _now()
            policy.ingestion_job_id = request.ingestion_job_id
            ready.append(policy)
            _audit(db, request.organisation_id, "policy.index_ready", policy)
        else:
            policy.index_status = IndexStatus.FAILED.value
            policy.index_error = (request.error or "Indexing failed.")[:500]
            policy.ingestion_job_id = request.ingestion_job_id
            _audit(db, request.organisation_id, "policy.index_failed", policy,
                   reason=policy.index_error)
    db.flush()
    _remove_superseded(db, kb, request.organisation_id, ready)


def _remove_superseded(
    db: Session, kb: KnowledgeBase, organisation_id: uuid.UUID, ready: list[PolicyDocument]
) -> None:
    """Once a revision is Ready, delete the objects of the older versions it replaced."""
    removed = False
    for policy in ready:
        if policy.status != PolicyStatus.APPROVED.value:
            continue
        older = db.execute(
            select(PolicyDocument).where(
                PolicyDocument.family_id == policy.family_id,
                PolicyDocument.id != policy.id,
                PolicyDocument.version < policy.version,
                PolicyDocument.approved_key.is_not(None),
            )
        ).scalars().all()
        for old in older:
            try:
                kb.delete_document(old.approved_key or "")
            except KnowledgeBaseError:
                log.warning("kb.cleanup_failed", extra={"policy_id": str(old.id)})
                continue  # reconcile will retry
            old.approved_key = None
            old.index_status = IndexStatus.NOT_INDEXED.value
            removed = True
    db.flush()
    if removed and kb.name != "keyword":
        request_sync(db, kb, organisation_id, "cleanup")


def poll(db: Session, kb: KnowledgeBase, organisation_id: uuid.UUID | None = None) -> int:
    """Update running sync requests; start queued ones. Returns how many finished."""
    stmt = select(KbSyncRequest).where(KbSyncRequest.status == SyncState.RUNNING.value)
    if organisation_id is not None:
        stmt = stmt.where(KbSyncRequest.organisation_id == organisation_id)
    finished = 0
    for request in db.execute(stmt).scalars().all():
        try:
            status = kb.get_sync_status(SyncHandle(job_id=request.ingestion_job_id))
        except KnowledgeBaseError as exc:
            log.warning("kb.poll_failed", extra={"sync_request_id": str(request.id),
                                                 "error": str(exc)[:200]})
            continue
        if status.state == JobState.RUNNING:
            continue
        request.finished_at = _now()
        if status.state == JobState.COMPLETE and status.failed_documents == 0:
            request.status = SyncState.COMPLETE.value
        elif status.state == JobState.COMPLETE:
            request.status = SyncState.COMPLETE.value
            request.error = (
                f"documents failed: {status.failed_documents} file(s) could not be indexed. "
                "Check the file has readable text, then reindex."
            )
        else:
            request.status = SyncState.FAILED.value
            request.error = (status.error or "Indexing failed.")[:500]
        db.flush()
        _settle(db, kb, request)
        finished += 1

    orgs = {organisation_id} if organisation_id else set(db.execute(
        select(KbSyncRequest.organisation_id).where(
            KbSyncRequest.status == SyncState.QUEUED.value)
    ).scalars().all())
    for org in orgs:
        if org is None or _active(db, org, SyncState.RUNNING) is not None:
            continue
        queued = _active(db, org, SyncState.QUEUED)
        if queued is not None:
            _start(db, kb, queued)
    return finished


def reconcile(db: Session, kb: KnowledgeBase, *, load_source: SourceLoader) -> list[str]:
    """Compare approved/ with the policies that should be there, and fix differences.

    Returns a list of short correction notes (ids only, no policy text) that are also logged.
    """
    present = kb.list_documents()
    if present is None:
        return []  # keyword backend: nothing to reconcile
    expected = db.execute(
        select(PolicyDocument).where(PolicyDocument.approved_key.is_not(None))
    ).scalars().all()
    expected_keys = {p.approved_key for p in expected}
    corrections: list[str] = []
    touched_orgs: dict[uuid.UUID, list[PolicyDocument]] = {}

    for key in sorted(present - expected_keys):  # orphans (e.g. a failed delete)
        try:
            kb.delete_document(key)
            corrections.append(f"removed orphan object {key}")
        except KnowledgeBaseError:
            corrections.append(f"could not remove orphan object {key}")

    approved = db.execute(
        select(PolicyDocument).where(PolicyDocument.status == PolicyStatus.APPROVED.value)
    ).scalars().all()
    for policy in approved:
        if policy.approved_key in present:
            continue
        data, extension, content_type = load_source(policy)
        try:
            policy.approved_key = kb.put_document(
                metadata_for(policy), data, extension=extension, content_type=content_type
            )
        except KnowledgeBaseError as exc:
            policy.index_status = IndexStatus.FAILED.value
            policy.index_error = str(exc)[:500]
            corrections.append(f"could not restore policy {policy.id}")
            continue
        policy.index_status = IndexStatus.INDEXING.value
        touched_orgs.setdefault(policy.organisation_id, []).append(policy)
        corrections.append(f"restored missing object for policy {policy.id}")

    for policy in expected:
        if policy.status == PolicyStatus.RETIRED.value and policy.approved_key in present:
            # A retired version with no newer approved version in the family must go.
            newer = db.execute(
                select(PolicyDocument.id).where(
                    PolicyDocument.family_id == policy.family_id,
                    PolicyDocument.status == PolicyStatus.APPROVED.value,
                    PolicyDocument.version > policy.version,
                    PolicyDocument.index_status != IndexStatus.READY.value,
                )
            ).first()
            if newer is None:
                try:
                    kb.delete_document(policy.approved_key or "")
                except KnowledgeBaseError:
                    continue
                policy.approved_key = None
                policy.index_status = IndexStatus.NOT_INDEXED.value
                touched_orgs.setdefault(policy.organisation_id, [])
                corrections.append(f"removed retired object for policy {policy.id}")

    db.flush()
    for org, policies in touched_orgs.items():
        request_sync(db, kb, org, "reconcile", policies)
    for note in corrections:
        log.info("kb.reconcile_correction", extra={"note": note})
    return corrections


def metadata_for(policy: PolicyDocument) -> PolicyMetadata:
    return PolicyMetadata(
        organisation_id=policy.organisation_id, policy_id=policy.id, version=policy.version,
        title=policy.title, kind=policy.kind, audience=list(policy.audience or ["everyone"]),
        effective_date=policy.effective_date,
    )
