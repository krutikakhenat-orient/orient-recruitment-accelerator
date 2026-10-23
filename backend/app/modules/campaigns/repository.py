"""Campaign data access. All queries are organisation-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.campaigns.models import Campaign


def create(db: Session, campaign: Campaign) -> Campaign:
    db.add(campaign)
    db.flush()
    return campaign


def get(db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID) -> Campaign | None:
    stmt = select(Campaign).where(
        Campaign.id == campaign_id, Campaign.organisation_id == organisation_id
    )
    return db.execute(stmt).scalars().first()


def list_for_org(
    db: Session, organisation_id: uuid.UUID, *, limit: int, offset: int
) -> list[Campaign]:
    stmt = (
        select(Campaign)
        .where(Campaign.organisation_id == organisation_id)
        .order_by(Campaign.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars())
