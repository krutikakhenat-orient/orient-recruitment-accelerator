"""Talent-pool HTTP router (thin). Requires talent_pool.search."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import requires
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.talent_pool import service

router = APIRouter(prefix="/api/v1/talent-pool", tags=["talent-pool"])


class TalentMatchRead(BaseModel):
    candidate_id: uuid.UUID
    full_name: str
    email: str
    note: str


@router.get("/search", response_model=list[TalentMatchRead])
def search(
    skill: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.TALENT_POOL_SEARCH)),
) -> list[TalentMatchRead]:
    matches = service.search(
        db, organisation_id=actor.organisation_id, actor_id=actor.user_id, skill_token=skill
    )
    return [
        TalentMatchRead(candidate_id=m.candidate_id, full_name=m.full_name,
                        email=m.email, note=m.note)
        for m in matches
    ]
