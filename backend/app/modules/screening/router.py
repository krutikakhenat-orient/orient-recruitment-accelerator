"""Screening HTTP router (thin). Executing a screening requires screening.execute and
object-level campaign authorisation. Each call creates a NEW immutable run."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import ConflictError
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.rules import repository as rules_repo
from app.modules.screening import service
from app.modules.screening.models import ScreeningRun
from app.modules.screening.schemas import ScreeningRunRead

router = APIRouter(prefix="/api/v1/screening", tags=["screening"])


@router.post("/applications/{application_id}/run", response_model=ScreeningRunRead,
             status_code=201)
def run_screening(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ScreeningRunRead:
    application = application_service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.SCREENING_EXECUTE, application.campaign_id)

    rule_version = rules_repo.latest_approved_rule_set_version(
        db, actor.organisation_id, application.campaign_id
    )
    if rule_version is None:
        raise ConflictError("No approved rule-set version exists for this campaign")
    threshold_version = rules_repo.latest_approved_threshold_version(
        db, actor.organisation_id, application.campaign_id
    )

    result = service.execute_for_application(
        db, organisation_id=actor.organisation_id, application=application,
        rule_set_version=rule_version, threshold_version=threshold_version, actor=actor,
    )
    return ScreeningRunRead.model_validate(result.run)


@router.get("/applications/{application_id}/runs", response_model=list[ScreeningRunRead])
def list_runs(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[ScreeningRunRead]:
    application = application_service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, application.campaign_id)
    stmt = (
        select(ScreeningRun)
        .where(
            ScreeningRun.organisation_id == actor.organisation_id,
            ScreeningRun.application_id == application_id,
        )
        .order_by(ScreeningRun.started_at.desc(), ScreeningRun.id.desc())
    )
    runs = db.execute(stmt).scalars().all()
    return [ScreeningRunRead.model_validate(r) for r in runs]
