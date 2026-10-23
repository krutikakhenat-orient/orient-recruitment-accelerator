"""Projects application service."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.projects import repository as repo
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate


def create_project(
    db: Session,
    organisation_id: uuid.UUID,
    data: ProjectCreate,
    actor_id: uuid.UUID,
) -> Project:
    if (
        data.planned_hiring_start
        and data.planned_hiring_end
        and data.planned_hiring_end < data.planned_hiring_start
    ):
        raise ValidationError("planned_hiring_end cannot be before planned_hiring_start")

    project = Project(
        organisation_id=organisation_id,
        name=data.name,
        business_unit=data.business_unit,
        department=data.department,
        business_owner=data.business_owner,
        hr_owner=data.hr_owner,
        description=data.description,
        planned_hiring_start=data.planned_hiring_start,
        planned_hiring_end=data.planned_hiring_end,
        status="active",
        created_by=actor_id,
        updated_by=actor_id,
    )
    project = repo.create(db, project)
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="project.created",
            entity_type="project",
            entity_id=str(project.id),
            new_state_ref="active",
        ),
    )
    return project


def get_project(
    db: Session, organisation_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = repo.get(db, organisation_id, project_id)
    if project is None:
        raise NotFoundError("Project not found")
    return project
