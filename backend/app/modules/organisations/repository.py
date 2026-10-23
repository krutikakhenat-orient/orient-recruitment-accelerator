"""Organisation data access.

MVP is single-organisation (ADR-0016). ``get_default_organisation`` returns the single
active organisation, creating a stable boundary for all scoped queries.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.identity.models import Organisation


def get_default_organisation(db: Session) -> Organisation:
    stmt = select(Organisation).where(Organisation.is_active.is_(True)).order_by(
        Organisation.created_at.asc()
    )
    org = db.execute(stmt).scalars().first()
    if org is None:
        raise NotFoundError("No active organisation is configured")
    return org


def get_or_create_organisation(db: Session, name: str) -> Organisation:
    stmt = select(Organisation).where(Organisation.name == name)
    org = db.execute(stmt).scalars().first()
    if org is None:
        org = Organisation(name=name, is_active=True)
        db.add(org)
        db.flush()
    return org
