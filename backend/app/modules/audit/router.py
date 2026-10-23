"""Audit HTTP router (read-only; requires audit.view)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.db.session import get_db
from app.modules.audit.models import AuditEvent
from app.modules.audit.schemas import AuditEventRead
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventRead])
def list_events(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.AUDIT_VIEW)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AuditEventRead]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.organisation_id == actor.organisation_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).scalars().all()
    return [AuditEventRead.model_validate(row) for row in rows]
