"""Projects application service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.projects import repository as repo
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


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


def update_project(
    db: Session,
    organisation_id: uuid.UUID,
    project_id: uuid.UUID,
    data: ProjectUpdate,
    actor_id: uuid.UUID,
) -> Project:
    """Edit a project's details. Only fields present in ``data`` are changed. Org-scoped
    and audited. Validates the planned-hiring date order against the resulting values."""
    project = get_project(db, organisation_id, project_id)

    fields = data.model_dump(exclude_unset=True)
    # Validate date ordering against the merged (new-or-existing) values.
    start = fields.get("planned_hiring_start", project.planned_hiring_start)
    end = fields.get("planned_hiring_end", project.planned_hiring_end)
    if start and end and end < start:
        raise ValidationError("planned_hiring_end cannot be before planned_hiring_start")

    for key, value in fields.items():
        setattr(project, key, value)
    project.updated_by = actor_id
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="project.updated",
            entity_type="project",
            entity_id=str(project.id),
            reason="fields updated: " + ", ".join(sorted(fields)) if fields else "no change",
        ),
    )
    return project


def delete_project(
    db: Session,
    organisation_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> tuple[int, int]:
    """Hard-delete a project AND every campaign inside it, with all their data.

    Destructive and high-impact: for each campaign in the project this reuses the proven
    campaign hard-delete (applications, screening/review history, interviews, assessments,
    decisions, waitlist, JD/rules/threshold/form config, assignments), then removes the
    project row. Gated on project.create at the router and requires a typed confirmation in
    the UI. Emits a ``project.deleted`` audit event recording how much was removed.

    Returns (campaigns_removed, applications_removed).
    """
    from app.modules.campaigns import service as campaign_service
    from app.modules.campaigns.models import Campaign

    project = get_project(db, organisation_id, project_id)

    campaigns = list(
        db.execute(
            select(Campaign).where(
                Campaign.organisation_id == organisation_id,
                Campaign.project_id == project.id,
            )
        ).scalars()
    )

    applications_removed = 0
    for campaign in campaigns:
        # Reuse the campaign cascade. Authorisation is at the PROJECT level (checked in the
        # router); we deliberately do NOT require per-campaign assignment here, because
        # deleting the project is an owner-level action over all its campaigns.
        applications_removed += campaign_service.delete_campaign(
            db, organisation_id=organisation_id, campaign=campaign, actor_id=actor_id
        )

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="project.deleted",
            entity_type="project",
            entity_id=str(project.id),
            previous_state_ref=project.status,
            reason=(
                f"hard delete; removed {len(campaigns)} campaign(s) and "
                f"{applications_removed} application(s) with all related data"
            ),
        ),
    )

    db.delete(project)
    db.flush()
    return len(campaigns), applications_removed
