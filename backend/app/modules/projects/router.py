"""Projects HTTP router (thin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, requires
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.projects import repository as repo
from app.modules.projects import service
from app.modules.projects.schemas import ProjectCreate, ProjectRead

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(requires(Permission.PROJECT_CREATE)),
) -> ProjectRead:
    project = service.create_project(db, actor.organisation_id, payload, actor.user_id)
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectRead]:
    projects = repo.list_for_org(db, actor.organisation_id, limit=limit, offset=offset)
    return [ProjectRead.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ProjectRead:
    project = service.get_project(db, actor.organisation_id, project_id)
    return ProjectRead.model_validate(project)
