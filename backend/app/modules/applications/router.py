"""Application HTTP routers.

The public submission endpoint is unauthenticated (candidates apply publicly) but is rate
-limitable and strictly validated. Internal endpoints (view application, review/correct
extracted fields) require authentication and object-level campaign authorisation.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import ValidationError
from app.db.session import get_db
from app.modules.applications import service
from app.modules.applications.schemas import (
    ApplicationRead,
    ApplicationStatusResponse,
    ExtractedFieldRead,
    FieldVerifyRequest,
    RankedApplicationRead,
    ResumePreviewResponse,
    SubmissionResponse,
    WalkInIntakeResponse,
    WalkInIntakeResult,
)
from app.modules.campaigns import service as campaign_service
from app.modules.campaigns.schemas import PublicRoleRead
from app.modules.extraction import service as extraction_service
from app.modules.forms import service as forms_service
from app.modules.forms.schemas import FormVersionRead
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.organisations.repository import get_default_organisation
from app.modules.screening.service import INITIAL_SUBMISSION_MESSAGE

# Public, unauthenticated candidate-facing endpoint.
public_router = APIRouter(prefix="/api/v1/public", tags=["public-applications"])
# Authenticated staff-facing endpoints.
router = APIRouter(prefix="/api/v1/applications", tags=["applications"])


@public_router.get("/open-roles", response_model=list[PublicRoleRead])
def list_open_roles(
    request: Request,  # noqa: ARG001 - available for rate-limiting middleware
    db: Session = Depends(get_db),
) -> list[PublicRoleRead]:
    """Public, unauthenticated list of roles currently open for applications.

    Powers the consolidated careers link's role dropdown. Returns only open campaigns that
    have an approved form, and exposes only candidate-facing fields (no internal data). Safe
    to serve anonymously; it is rate-limitable like the other public endpoints.
    """
    org = get_default_organisation(db)
    roles = campaign_service.list_open_roles(db, org.id)
    return [
        PublicRoleRead(
            id=c.id,
            title=c.position_title,
            location=c.work_location,
            employment_type=c.employment_type,
            work_mode=c.work_mode,
        )
        for c in roles
    ]


@public_router.get("/campaigns/{campaign_id}/form", response_model=FormVersionRead)
def get_public_form(
    campaign_id: uuid.UUID,
    request: Request,  # noqa: ARG001 - available for rate-limiting middleware
    db: Session = Depends(get_db),
) -> FormVersionRead:
    """The approved application form for an open role, for the public form renderer.

    Only returns a form for a campaign that is currently open AND has an approved form; a
    closed/invalid role yields 404/409 so a candidate can never submit against it.
    """
    org = get_default_organisation(db)
    campaign = campaign_service.get_campaign(db, org.id, campaign_id)
    if campaign.state not in campaign_service.PUBLIC_OPEN_STATES:
        raise ValidationError("This role is not currently accepting applications")
    if campaign.approved_form_version_id is None:
        raise ValidationError("This role has no application form yet")
    version = forms_service.get_approved_form_version(
        db, organisation_id=org.id, form_version_id=campaign.approved_form_version_id
    )
    return FormVersionRead.model_validate(version)


@public_router.post("/campaigns/{campaign_id}/apply", response_model=SubmissionResponse,
                    status_code=201)
async def apply(
    campaign_id: uuid.UUID,
    request: Request,  # noqa: ARG001 - available for rate-limiting middleware
    answers: str = Form(..., description="JSON object of form answers"),
    resume: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> SubmissionResponse:
    try:
        parsed_answers = json.loads(answers)
    except json.JSONDecodeError as exc:
        raise ValidationError("answers must be a valid JSON object") from exc
    if not isinstance(parsed_answers, dict):
        raise ValidationError("answers must be a JSON object")

    data = await resume.read()
    if not data:
        raise ValidationError("A resume file is required")

    org = get_default_organisation(db)
    result = service.submit_application(
        db,
        organisation_id=org.id,
        campaign_id=campaign_id,
        answers=parsed_answers,
        resume_filename=resume.filename or "resume",
        resume_content_type=resume.content_type or "",
        resume_bytes=data,
    )
    return SubmissionResponse(
        application_id=result.application.id,
        state=result.application.state,
        manual_review=result.manual_review,
        # Stage 1 (meeting requirement): the immediate confirmation shown on successful
        # submission, BEFORE any score-based result. The score-based message is fetched
        # separately from the status endpoint once scoring has completed.
        message=INITIAL_SUBMISSION_MESSAGE,
    )


@public_router.post("/resume-preview", response_model=ResumePreviewResponse)
async def resume_preview(
    request: Request,  # noqa: ARG001 - available for rate-limiting middleware
    resume: UploadFile = File(...),
    db: Session = Depends(get_db),  # noqa: ARG001 - kept for parity / future rate-limit hooks
) -> ResumePreviewResponse:
    """Parse an uploaded resume and return suggested form answers for the candidate to
    review before they finish the application. Unauthenticated (part of the public apply
    flow), read-only: nothing is stored, no candidate record is created, no screening runs.
    The candidate edits every suggested value and fills the rest."""
    data = await resume.read()
    if not data:
        raise ValidationError("A resume file is required")
    preview = service.preview_resume_fields(
        resume_filename=resume.filename or "resume",
        resume_content_type=resume.content_type or "",
        resume_bytes=data,
    )
    return ResumePreviewResponse(extracted=preview.extracted, fields=preview.fields)


@public_router.get(
    "/applications/{application_id}/status", response_model=ApplicationStatusResponse
)
def application_status(
    application_id: uuid.UUID,
    request: Request,  # noqa: ARG001 - available for rate-limiting middleware
    db: Session = Depends(get_db),
) -> ApplicationStatusResponse:
    """Public, candidate-facing screening status for the application screen (stage 2).

    The candidate holds their own ``application_id`` (returned at submission) and polls this
    to learn when scoring is complete. It returns ONLY a coarse status and the candidate
    message derived from the actual saved score — never the raw score, evidence,
    recommendation or internal notes (privacy preserved). Unknown ids yield a neutral
    pending response rather than confirming/denying existence (no enumeration signal).
    """
    org = get_default_organisation(db)
    status = service.public_application_status(db, org.id, application_id)
    if status is None:
        # Do not reveal whether an id exists; a candidate with a valid id always gets a real
        # status, while a bad id simply stays on the initial thank-you message.
        return ApplicationStatusResponse(
            status="pending", message=INITIAL_SUBMISSION_MESSAGE
        )
    return ApplicationStatusResponse(status=status.status, message=status.message)


@router.post("/walk-in-intake", response_model=WalkInIntakeResponse, status_code=201)
async def walk_in_bulk_intake(
    campaign_id: uuid.UUID = Form(...),
    consent_attested: bool = Form(
        ..., description="Recruiter attests walk-in candidates gave consent at the drive"
    ),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> WalkInIntakeResponse:
    """Bulk-ingest walk-in resumes for a campaign (safe document pipeline per file).

    Requires screening.execute + campaign assignment. The recruiter must attest that
    walk-in candidates consented to processing (privacy.md: consent is never assumed). This
    validates, scans and quarantines each file; it does not create candidate records or run
    screening — identity and purpose-specific consent are captured in a later step.
    """
    require_campaign_permission(actor, Permission.SCREENING_EXECUTE, campaign_id)
    if not consent_attested:
        raise ValidationError(
            "Consent attestation is required before ingesting walk-in resumes"
        )
    if not files:
        raise ValidationError("At least one resume file is required")

    payloads: list[tuple[str, str, bytes]] = []
    for f in files:
        data = await f.read()
        payloads.append((f.filename or "resume", f.content_type or "", data))

    items = service.bulk_intake_walk_in_resumes(
        db,
        organisation_id=actor.organisation_id,
        campaign_id=campaign_id,
        actor_id=actor.user_id,
        resumes=payloads,
    )
    results = [
        WalkInIntakeResult(
            filename=i.filename, accepted=i.accepted, application_id=i.application_id,
            duplicate=i.duplicate, detail=i.detail, score=i.score,
            manual_review=i.manual_review,
        )
        for i in items
    ]
    accepted = sum(1 for i in items if i.accepted)
    return WalkInIntakeResponse(
        campaign_id=campaign_id,
        total=len(items),
        accepted=accepted,
        rejected=len(items) - accepted,
        results=results,
    )


@router.get("", response_model=list[RankedApplicationRead])
def list_applications(
    campaign_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RankedApplicationRead]:
    # Viewing a campaign's applications requires candidate.view + campaign assignment.
    # Returns candidates RANKED by latest-run fit score (desc), scoped to this campaign,
    # with the latest-run summary embedded so the UI needs no per-candidate score calls.
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, campaign_id)
    ranked = service.list_ranked_for_campaign(
        db, actor.organisation_id, campaign_id, limit=limit, offset=offset
    )
    return [
        RankedApplicationRead(
            id=r.application.id,
            organisation_id=r.application.organisation_id,
            campaign_id=r.application.campaign_id,
            candidate_id=r.application.candidate_id,
            state=r.application.state,
            answers=r.application.answers,
            version=r.application.version,
            rank=r.rank,
            scored=r.scored,
            score=r.score,
            recommendation=r.recommendation,
            manual_review_required=r.manual_review_required,
            conflict_flagged=r.conflict_flagged,
            latest_run_id=r.latest_run_id,
        )
        for r in ranked
    ]


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ApplicationRead:
    app = service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, app.campaign_id)
    return ApplicationRead.model_validate(app)


@router.get("/{application_id}/extracted-fields", response_model=list[ExtractedFieldRead])
def list_extracted_fields(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[ExtractedFieldRead]:
    app = service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, app.campaign_id)
    fields = extraction_service.list_fields(db, actor.organisation_id, application_id)
    return [ExtractedFieldRead.model_validate(f) for f in fields]


@router.post("/{application_id}/extracted-fields/{field_id}/verify",
             response_model=ExtractedFieldRead)
def verify_field(
    application_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: FieldVerifyRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ExtractedFieldRead:
    app = service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.CANDIDATE_CORRECT, app.campaign_id)
    field = extraction_service.verify_field(
        db,
        organisation_id=actor.organisation_id,
        field_id=field_id,
        actor_id=actor.user_id,
        corrected_value=payload.corrected_value,
        correction_reason=payload.correction_reason,
    )
    return ExtractedFieldRead.model_validate(field)
