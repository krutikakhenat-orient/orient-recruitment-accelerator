"""Policy library HTTP router (thin).

Reading approved policies and acknowledging them is open to every signed-in user, limited
to the policies whose audience includes them. Managing the library needs campaign.approve
(HR sign-off); managers also see drafts and retired versions. The assistant endpoints live
in ``app.modules.assistant.router``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, settings_dep
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.documents.scanning import MalwareScanner
from app.modules.documents.storage import ObjectStore
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import has_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.knowledge_base.deps import (
    get_knowledge_base,
    get_malware_scanner,
    get_policy_file_store,
)
from app.modules.knowledge_base.types import KnowledgeBase
from app.modules.policies import service
from app.modules.policies.audience import actor_audience, parse_audience_field
from app.modules.policies.models import PolicyStatus
from app.modules.policies.schemas import IndexStatusRead, PolicyCreate, PolicyRead, PolicyUpdate

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])

_KIND_PATTERN = "^(policy|sop|faq)$"


class OriginalLink(BaseModel):
    url: str | None
    expires_in: int | None


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    # Read one byte past the cap so an oversize file is rejected without buffering it all.
    return await upload.read(max_bytes + 1)


@router.get("", response_model=list[PolicyRead])
def list_policies(
    department: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[PolicyRead]:
    """Any signed-in user. Managers (campaign.approve) also see drafts and retired versions."""
    manager = has_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.list_policies(db, actor, manager=manager, department=department)


@router.post("", response_model=PolicyRead, status_code=201)
def create_policy(
    payload: PolicyCreate,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Type in a policy, SOP or FAQ as a draft. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.create_policy(
        db, actor=actor, store=store, title=payload.title, kind=payload.kind,
        department=payload.department, body=payload.body, effective_date=payload.effective_date,
        audience=payload.audience, review_due_date=payload.review_due_date,
    )
    return service.read_policy(db, actor, policy)


@router.post("/upload", response_model=PolicyRead, status_code=201)
async def upload_policy(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=255),
    kind: str = Form(default="policy", pattern=_KIND_PATTERN),
    department: str | None = Form(default=None, max_length=120),
    audience: str | None = Form(default=None, max_length=600),
    effective_date: dt.date | None = Form(default=None),
    review_due_date: dt.date | None = Form(default=None),
    confirm_duplicate: bool = Form(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    store: ObjectStore = Depends(get_policy_file_store),
    scanner: MalwareScanner = Depends(get_malware_scanner),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Upload a PDF, DOCX, TXT or MD file as a draft. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    data = await _read_capped(file, settings.upload_max_bytes)
    policy = service.upload_policy(
        db, actor=actor, store=store, scanner=scanner, filename=file.filename or "",
        declared_content_type=file.content_type or "", data=data,
        max_bytes=settings.upload_max_bytes, title=title, kind=kind, department=department,
        audience=parse_audience_field(audience), effective_date=effective_date,
        review_due_date=review_due_date, confirm_duplicate=confirm_duplicate,
    )
    return service.read_policy(db, actor, policy)


@router.post("/{policy_id}/file", response_model=PolicyRead)
async def replace_file(
    policy_id: uuid.UUID,
    file: UploadFile = File(...),
    confirm_duplicate: bool = Form(default=False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    store: ObjectStore = Depends(get_policy_file_store),
    scanner: MalwareScanner = Depends(get_malware_scanner),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Replace the file of a draft. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    data = await _read_capped(file, settings.upload_max_bytes)
    service.replace_file(
        db, actor=actor, store=store, scanner=scanner, policy=policy,
        filename=file.filename or "", declared_content_type=file.content_type or "",
        data=data, max_bytes=settings.upload_max_bytes, confirm_duplicate=confirm_duplicate,
    )
    return service.read_policy(db, actor, policy)


@router.put("/{policy_id}", response_model=PolicyRead)
def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Edit a draft. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.update_policy(
        db, actor=actor, store=store, policy=policy,
        changes=payload.model_dump(exclude_unset=True),
    )
    return service.read_policy(db, actor, policy)


@router.post("/{policy_id}/approve", response_model=PolicyRead)
def approve_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    kb: KnowledgeBase = Depends(get_knowledge_base),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Approve a draft and send it for indexing. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.approve_policy(db, actor=actor, policy=policy, store=store, kb=kb)
    return service.read_policy(db, actor, policy)


@router.post("/{policy_id}/retire", response_model=PolicyRead)
def retire_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    kb: KnowledgeBase = Depends(get_knowledge_base),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Retire an approved policy and remove it from the index. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.retire_policy(db, actor=actor, policy=policy, kb=kb)
    return service.read_policy(db, actor, policy)


@router.post("/{policy_id}/revise", response_model=PolicyRead, status_code=201)
def revise_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Start a new draft version of an approved policy. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    draft = service.revise_policy(db, actor=actor, policy=policy, store=store)
    return service.read_policy(db, actor, draft)


@router.post("/{policy_id}/reindex", response_model=PolicyRead)
def reindex_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    kb: KnowledgeBase = Depends(get_knowledge_base),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Retry indexing an approved policy. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.reindex_policy(db, actor=actor, policy=policy, store=store, kb=kb)
    return service.read_policy(db, actor, policy)


@router.get("/{policy_id}/index-status", response_model=IndexStatusRead)
def index_status(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    kb: KnowledgeBase = Depends(get_knowledge_base),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> IndexStatusRead:
    """Whether the chatbot can use this version yet. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    return service.index_status(db, policy=policy, kb=kb)


@router.get("/{policy_id}/original-link", response_model=OriginalLink)
def original_link(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> OriginalLink:
    """Short-lived signed link to the stored file when the store supports one (S3);
    otherwise url is null and the client uses /original. Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    if not policy.source_key:
        raise NotFoundError("This policy has no stored file.")
    presign = getattr(store, "presigned_get_url", None)
    if presign is None:
        return OriginalLink(url=None, expires_in=None)
    ttl = min(settings.signed_url_ttl_seconds, 900)
    url = presign(policy.source_key, policy.source_content_type or "application/octet-stream", ttl)
    return OriginalLink(url=url, expires_in=ttl)


@router.get("/{policy_id}/original")
def original_file(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_policy_file_store),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> Response:
    """Download the stored file (as an attachment, never rendered inline).
    Requires campaign.approve."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    data, content_type, name = service.original_file(store, policy)
    return Response(
        content=data, media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post("/{policy_id}/acknowledge", response_model=PolicyRead)
def acknowledge_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Record that the signed-in person has read this version of the policy."""
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    manager = has_permission(actor, Permission.CAMPAIGN_APPROVE)
    if not manager and (
        policy.status != PolicyStatus.APPROVED.value
        or not actor_audience(actor).allows(policy.audience)
    ):
        raise NotFoundError("Policy not found")
    service.acknowledge(db, actor=actor, policy=policy)
    return service.read_policy(db, actor, policy)
