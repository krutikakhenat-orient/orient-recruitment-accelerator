"""Job Description HTTP router (thin). Uploads enforce object-level campaign authz."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import ValidationError
from app.db.session import get_db
from app.modules.campaigns import service as campaign_service
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.job_descriptions import service
from app.modules.job_descriptions.schemas import (
    JDApprove,
    JDVersionRead,
    JDVersionUpdate,
)

router = APIRouter(prefix="/api/v1/job-descriptions", tags=["job-descriptions"])


@router.get("/versions", response_model=list[JDVersionRead])
def list_versions(
    campaign_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[JDVersionRead]:
    """List a campaign's JD versions (newest first) so reviewers can approve an existing
    draft without having uploaded it themselves. Requires JD review + campaign access."""
    require_campaign_permission(actor, Permission.JD_REVIEW, campaign_id)
    versions = service.list_versions_for_campaign(db, actor.organisation_id, campaign_id)
    return [JDVersionRead.model_validate(v) for v in versions]


@router.post("/upload", response_model=JDVersionRead, status_code=201)
async def upload_jd(
    campaign_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> JDVersionRead:
    require_campaign_permission(actor, Permission.JD_UPLOAD, campaign_id)
    # Verify the campaign exists in this org.
    campaign_service.get_campaign(db, actor.organisation_id, campaign_id)

    data = await file.read()
    if not data:
        raise ValidationError("Uploaded file is empty")
    version = service.upload_jd(
        db,
        organisation_id=actor.organisation_id,
        campaign_id=campaign_id,
        actor_id=actor.user_id,
        filename=file.filename or "upload",
        declared_content_type=file.content_type or "",
        data=data,
    )
    return JDVersionRead.model_validate(version)


@router.patch("/versions/{jd_version_id}", response_model=JDVersionRead)
def update_version(
    jd_version_id: uuid.UUID,
    payload: JDVersionUpdate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> JDVersionRead:
    require_permission(actor, Permission.JD_REVIEW)
    version = service.update_jd_version(
        db,
        organisation_id=actor.organisation_id,
        jd_version_id=jd_version_id,
        actor_id=actor.user_id,
        data=payload,
    )
    return JDVersionRead.model_validate(version)


@router.get("/versions/pending", response_model=list[JDVersionRead])
def list_pending(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[JDVersionRead]:
    """Draft JD versions awaiting the current approver's decision, restricted to the
    campaigns they're assigned to. Requires JD approval permission."""
    require_permission(actor, Permission.JD_APPROVE)
    versions = service.list_pending_versions(
        db, actor.organisation_id, campaign_ids=actor.assigned_campaign_ids
    )
    return [JDVersionRead.model_validate(v) for v in versions]


@router.post("/versions/{jd_version_id}/approve", response_model=JDVersionRead)
def approve_version(
    jd_version_id: uuid.UUID,
    payload: JDApprove,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> JDVersionRead:
    require_permission(actor, Permission.JD_APPROVE)
    version = service.approve_jd_version(
        db,
        organisation_id=actor.organisation_id,
        jd_version_id=jd_version_id,
        actor_id=actor.user_id,
        change_reason=payload.change_reason,
    )
    return JDVersionRead.model_validate(version)


@router.post("/versions/{jd_version_id}/reject", response_model=JDVersionRead)
def reject_version(
    jd_version_id: uuid.UUID,
    payload: JDApprove,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> JDVersionRead:
    require_permission(actor, Permission.JD_APPROVE)
    version = service.reject_jd_version(
        db,
        organisation_id=actor.organisation_id,
        jd_version_id=jd_version_id,
        actor_id=actor.user_id,
        change_reason=payload.change_reason,
    )
    return JDVersionRead.model_validate(version)


@router.post("/versions/{jd_version_id}/revise", response_model=JDVersionRead, status_code=201)
def revise_version(
    jd_version_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> JDVersionRead:
    require_permission(actor, Permission.JD_REVIEW)
    version = service.revise_jd_version(
        db,
        organisation_id=actor.organisation_id,
        approved_version_id=jd_version_id,
        actor_id=actor.user_id,
    )
    return JDVersionRead.model_validate(version)
