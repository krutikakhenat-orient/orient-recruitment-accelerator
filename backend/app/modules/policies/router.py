"""Policy library and HR assistant HTTP routers (thin).

Reading approved policies, acknowledging them and asking the assistant is open to every
signed-in user (staff and employees). Managing the library needs campaign.approve (HR
sign-off). Reading it as a manager also shows drafts and retired versions.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import has_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.policies import service
from app.modules.policies.schemas import (
    AskRequest,
    AskResponse,
    PolicyCreate,
    PolicyRead,
    PolicyUpdate,
    UnansweredRead,
)

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])
assistant_router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


def _read(db: Session, actor: AuthenticatedActor, policy_id: uuid.UUID) -> PolicyRead:
    rows = service.list_policies(db, actor, manager=True)
    return next(r for r in rows if r.id == policy_id)


@router.get("", response_model=list[PolicyRead])
def list_policies(
    department: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[PolicyRead]:
    manager = has_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.list_policies(db, actor, manager=manager, department=department)


@router.post("", response_model=PolicyRead, status_code=201)
def create_policy(
    payload: PolicyCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.create_policy(
        db, actor=actor, title=payload.title, kind=payload.kind, department=payload.department,
        body=payload.body, effective_date=payload.effective_date,
    )
    return _read(db, actor, policy.id)


@router.put("/{policy_id}", response_model=PolicyRead)
def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.update_policy(
        db, actor=actor, policy=policy, changes=payload.model_dump(exclude_unset=True)
    )
    return _read(db, actor, policy.id)


@router.post("/{policy_id}/approve", response_model=PolicyRead)
def approve_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.approve_policy(db, actor=actor, policy=policy)
    return _read(db, actor, policy.id)


@router.post("/{policy_id}/retire", response_model=PolicyRead)
def retire_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.retire_policy(db, actor=actor, policy=policy)
    return _read(db, actor, policy.id)


@router.post("/{policy_id}/revise", response_model=PolicyRead, status_code=201)
def revise_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    draft = service.revise_policy(db, actor=actor, policy=policy)
    return _read(db, actor, draft.id)


@router.post("/{policy_id}/acknowledge", response_model=PolicyRead)
def acknowledge_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> PolicyRead:
    """Record that the signed-in person has read this version of the policy."""
    policy = service.get_policy(db, actor.organisation_id, policy_id)
    service.acknowledge(db, actor=actor, policy=policy)
    manager = has_permission(actor, Permission.CAMPAIGN_APPROVE)
    rows = service.list_policies(db, actor, manager=manager)
    return next(r for r in rows if r.id == policy.id)


@assistant_router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AskResponse:
    """Answer an HR question from approved policies only (no AI model involved)."""
    return service.ask(db, actor.organisation_id, payload.question)


@assistant_router.get("/unanswered", response_model=list[UnansweredRead])
def unanswered(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[UnansweredRead]:
    """Questions the assistant could not answer, so HR can add the missing policy."""
    require_permission(actor, Permission.CAMPAIGN_APPROVE)
    return service.list_unanswered(db, actor.organisation_id)
