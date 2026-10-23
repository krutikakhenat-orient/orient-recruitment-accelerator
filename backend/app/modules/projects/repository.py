"""Projects data access. All queries are organisation-scoped (Req: tenant scoping)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.projects.models import Project


def create(db: Session, project: Project) -> Project:
    db.add(project)
    db.flush()
    return project


def get(db: Session, organisation_id: uuid.UUID, project_id: uuid.UUID) -> Project | None:
    stmt = select(Project).where(
        Project.id == project_id, Project.organisation_id == organisation_id
    )
    return db.execute(stmt).scalars().first()


def list_for_org(
    db: Session, organisation_id: uuid.UUID, *, limit: int, offset: int
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.organisation_id == organisation_id)
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars())
