"""Job Description application service (Req 3.1-3.3).

Flow:
- upload_jd: ingest a scanned JD document, extract a suggested draft, and create a DRAFT
  JDVersion seeded with the suggestion (never authoritative on its own).
- update_jd_version: a reviewer edits the authoritative structured content (DRAFT only).
- approve_jd_version: freezes the version as APPROVED and IMMUTABLE.
- revise_jd_version: creates a NEW draft version cloned from an approved one (used when a
  JD changes after applications started); the original approved version is preserved.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.documents.models import DocumentKind
from app.modules.documents.service import ingest_document
from app.modules.extraction.jd_extractor import extract_jd_draft
from app.modules.extraction.text_extractors import extract_text
from app.modules.job_descriptions.models import (
    JDVersion,
    JDVersionStatus,
    JobDescription,
)
from app.modules.job_descriptions.schemas import JDVersionUpdate


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def list_versions_for_campaign(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[JDVersion]:
    """All JD versions for a campaign, newest first (for review/approval in the UI)."""
    jd = (
        db.execute(
            select(JobDescription).where(
                JobDescription.organisation_id == organisation_id,
                JobDescription.campaign_id == campaign_id,
            )
        )
        .scalars()
        .first()
    )
    if jd is None:
        return []
    stmt = (
        select(JDVersion)
        .where(JDVersion.job_description_id == jd.id)
        .order_by(JDVersion.version_number.desc())
    )
    return list(db.execute(stmt).scalars())


def _get_or_create_jd(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> JobDescription:
    stmt = select(JobDescription).where(
        JobDescription.organisation_id == organisation_id,
        JobDescription.campaign_id == campaign_id,
    )
    jd = db.execute(stmt).scalars().first()
    if jd is None:
        jd = JobDescription(organisation_id=organisation_id, campaign_id=campaign_id)
        db.add(jd)
        db.flush()
    return jd


def _next_version_number(db: Session, job_description_id: uuid.UUID) -> int:
    stmt = (
        select(JDVersion.version_number)
        .where(JDVersion.job_description_id == job_description_id)
        .order_by(JDVersion.version_number.desc())
        .limit(1)
    )
    latest = db.execute(stmt).scalars().first()
    return (latest or 0) + 1


def upload_jd(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID,
    filename: str,
    declared_content_type: str,
    data: bytes,
    logical_type_hint: str | None = None,
) -> JDVersion:
    # Safe upload (validate + quarantine + scan); raises on malicious/invalid files.
    document = ingest_document(
        db,
        organisation_id=organisation_id,
        actor_id=actor_id,
        kind=DocumentKind.JD,
        filename=filename,
        declared_content_type=declared_content_type,
        data=data,
    )

    # Extract text, then propose a structured draft (suggestion only).
    logical_type = logical_type_hint or document.content_type_to_logical()
    text_result = extract_text(logical_type, data)
    draft = extract_jd_draft(text_result.text if text_result.ok else "")

    jd = _get_or_create_jd(db, organisation_id, campaign_id)
    version = JDVersion(
        job_description_id=jd.id,
        organisation_id=organisation_id,
        version_number=_next_version_number(db, jd.id),
        status=JDVersionStatus.DRAFT.value,
        source_document_id=document.id,
        extraction_draft={
            "method": text_result.method,
            "ok": text_result.ok,
            "detail": text_result.detail,
            "fields": [
                {"name": f.name, "value": f.value, "confidence": f.confidence,
                 "source_span": f.source_span}
                for f in draft.fields
            ],
            "responsibilities": draft.responsibilities,
            "mandatory_skills": draft.mandatory_skills,
            "desirable_skills": draft.desirable_skills,
            "notes": draft.extraction_notes,
        },
        # Pre-fill authoritative fields from high-confidence suggestions; the reviewer
        # confirms/edits before approval. Lists are suggestions until reviewed.
        responsibilities=draft.responsibilities,
        mandatory_skills=draft.mandatory_skills,
        desirable_skills=draft.desirable_skills,
        created_by=actor_id,
    )
    _apply_proposed_scalars(version, draft)
    db.add(version)
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="jd_version.uploaded",
            entity_type="jd_version",
            entity_id=str(version.id),
            new_state_ref="draft",
            reason=f"document={document.id}; extraction_ok={text_result.ok}",
        ),
    )
    return version


def update_jd_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    jd_version_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: JDVersionUpdate,
) -> JDVersion:
    version = _load_version(db, organisation_id, jd_version_id)
    if version.is_approved:
        raise ConflictError("Approved JD versions are immutable; create a new version")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(version, key, value)
    version.updated_by = actor_id
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="jd_version.updated",
            entity_type="jd_version",
            entity_id=str(version.id),
        ),
    )
    return version


def approve_jd_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    jd_version_id: uuid.UUID,
    actor_id: uuid.UUID,
    change_reason: str,
) -> JDVersion:
    version = _load_version(db, organisation_id, jd_version_id)
    if version.is_approved:
        raise ConflictError("JD version is already approved and immutable")
    if not version.position_title:
        raise ValidationError("A position title is required before approving a JD version")

    version.status = JDVersionStatus.APPROVED.value
    version.approved_by = actor_id
    version.approved_at = _now()
    version.change_reason = change_reason
    db.flush()

    # Point the owning campaign at this now-approved JD version. Without this the campaign's
    # approved_jd_version_id stays null, so downstream steps that read it (e.g. "Generate
    # scoring rules from JD") would keep reporting "Approve a Job Description first" even
    # though a JD was approved. Any previously-approved JD version is superseded.
    from app.modules.campaigns.models import Campaign

    jd = db.get(JobDescription, version.job_description_id)
    if jd is not None and jd.organisation_id == organisation_id:
        campaign = db.get(Campaign, jd.campaign_id)
        if campaign is not None and campaign.organisation_id == organisation_id:
            previous = campaign.approved_jd_version_id
            if previous is not None and previous != version.id:
                prior = db.get(JDVersion, previous)
                if prior is not None and prior.status == JDVersionStatus.APPROVED.value:
                    prior.status = JDVersionStatus.SUPERSEDED.value
            campaign.approved_jd_version_id = version.id
            campaign.updated_by = actor_id
            db.flush()

            # Auto-generate, validate, save and approve scoring criteria from this JD, and
            # ensure the default 50% threshold — so HR does not have to configure a rule set
            # manually. Four-eyes is preserved (system authors, this human approves). If the
            # JD yields no usable criteria we DO NOT fall back to empty rules: the JD still
            # approves, but we record a manual-review warning and leave the campaign without
            # approved criteria (it cannot publish/screen until the JD is corrected).
            _auto_configure_criteria(
                db,
                organisation_id=organisation_id,
                campaign_id=campaign.id,
                actor_id=actor_id,
                jd_version_id=version.id,
            )

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="jd_version.approved",
            entity_type="jd_version",
            entity_id=str(version.id),
            previous_state_ref="draft",
            new_state_ref="approved",
            reason=change_reason,
        ),
    )
    return version


def _auto_configure_criteria(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID,
    jd_version_id: uuid.UUID,
) -> None:
    """Generate + approve JD-derived scoring criteria and ensure the default threshold.

    Delegates to rules.service (reuses the deterministic JD-derived rule builder and the
    existing four-eyes-aware approval). A JD that produces no usable criteria is NOT an
    error for the JD approval itself: it records a ``jd_version.criteria_generation_warning``
    audit event (so HR sees a manual-review signal) and leaves the campaign without approved
    criteria rather than inventing empty/misleading ones. Any other unexpected failure is
    also recorded as a warning and swallowed so a transient criteria issue never blocks a
    legitimate JD approval; HR can re-approve or fix the JD.
    """
    from app.core.errors import ValidationError as _ValidationError
    from app.modules.rules import service as rules_service

    try:
        rules_service.auto_generate_criteria_on_jd_approval(
            db,
            organisation_id=organisation_id,
            campaign_id=campaign_id,
            approver_id=actor_id,
        )
    except _ValidationError as exc:
        record_event(
            db,
            AuditEventWrite(
                organisation_id=organisation_id,
                actor_id=actor_id,
                action="jd_version.criteria_generation_warning",
                entity_type="jd_version",
                entity_id=str(jd_version_id),
                reason=(
                    "Automatic criteria generation incomplete — manual review required: "
                    f"{exc}"
                ),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - criteria generation must not block JD approval
        record_event(
            db,
            AuditEventWrite(
                organisation_id=organisation_id,
                actor_id=actor_id,
                action="jd_version.criteria_generation_warning",
                entity_type="jd_version",
                entity_id=str(jd_version_id),
                reason=f"Automatic criteria generation failed unexpectedly: {exc}",
            ),
        )


def reject_jd_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    jd_version_id: uuid.UUID,
    actor_id: uuid.UUID,
    change_reason: str,
) -> JDVersion:
    """Reject a DRAFT JD version. A reason is required; an approved version is immutable
    and cannot be rejected (create a new revision instead)."""
    version = _load_version(db, organisation_id, jd_version_id)
    if version.is_approved:
        raise ConflictError("An approved JD version is immutable; it cannot be rejected")
    if version.status == JDVersionStatus.REJECTED.value:
        raise ConflictError("JD version is already rejected")
    if not change_reason or not change_reason.strip():
        raise ValidationError("A reason is required to reject a JD version")
    version.status = JDVersionStatus.REJECTED.value
    version.approved_by = actor_id  # records who made the decision
    version.approved_at = _now()
    version.change_reason = change_reason
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="jd_version.rejected",
            entity_type="jd_version",
            entity_id=str(version.id),
            previous_state_ref="draft",
            new_state_ref="rejected",
            reason=change_reason,
        ),
    )
    return version


def list_pending_versions(
    db: Session, organisation_id: uuid.UUID, campaign_ids: set[uuid.UUID] | None = None
) -> list[JDVersion]:
    """Draft (pending-approval) JD versions org-wide, optionally restricted to a set of
    campaigns the approver is assigned to (object-level authorisation)."""
    stmt = (
        select(JDVersion)
        .join(JobDescription, JobDescription.id == JDVersion.job_description_id)
        .where(
            JDVersion.organisation_id == organisation_id,
            JDVersion.status == JDVersionStatus.DRAFT.value,
        )
        .order_by(JDVersion.created_at.desc())
    )
    versions = list(db.execute(stmt).scalars())
    if campaign_ids is not None:
        allowed = campaign_ids
        jd_campaign = {
            jd.id: jd.campaign_id
            for jd in db.execute(
                select(JobDescription).where(JobDescription.organisation_id == organisation_id)
            ).scalars()
        }
        versions = [v for v in versions if jd_campaign.get(v.job_description_id) in allowed]
    return versions


def campaign_id_for_version(
    db: Session, organisation_id: uuid.UUID, version: JDVersion
) -> uuid.UUID:
    """Resolve the owning campaign id for a JD version (for object-level authz)."""
    jd = db.get(JobDescription, version.job_description_id)
    if jd is None or jd.organisation_id != organisation_id:
        raise NotFoundError("Job description not found")
    return jd.campaign_id


def revise_jd_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    approved_version_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> JDVersion:
    """Create a new DRAFT cloned from an approved version (preserves the original)."""
    source = _load_version(db, organisation_id, approved_version_id)
    if not source.is_approved:
        raise ValidationError("Can only revise from an approved JD version")

    new_version = JDVersion(
        job_description_id=source.job_description_id,
        organisation_id=organisation_id,
        version_number=_next_version_number(db, source.job_description_id),
        status=JDVersionStatus.DRAFT.value,
        source_document_id=source.source_document_id,
        position_title=source.position_title,
        department=source.department,
        location=source.location,
        work_mode=source.work_mode,
        employment_type=source.employment_type,
        number_of_openings=source.number_of_openings,
        minimum_total_experience_years=source.minimum_total_experience_years,
        minimum_relevant_experience_years=source.minimum_relevant_experience_years,
        responsibilities=list(source.responsibilities),
        mandatory_skills=list(source.mandatory_skills),
        desirable_skills=list(source.desirable_skills),
        extraction_draft=source.extraction_draft,
        created_by=actor_id,
    )
    db.add(new_version)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="jd_version.revised",
            entity_type="jd_version",
            entity_id=str(new_version.id),
            previous_state_ref=str(source.id),
            new_state_ref="draft",
            reason="new version cloned from approved; original preserved",
        ),
    )
    return new_version


def _load_version(
    db: Session, organisation_id: uuid.UUID, jd_version_id: uuid.UUID
) -> JDVersion:
    version = db.get(JDVersion, jd_version_id)
    if version is None or version.organisation_id != organisation_id:
        raise NotFoundError("JD version not found")
    return version


def _apply_proposed_scalars(version: JDVersion, draft: object) -> None:
    """Pre-fill scalar authoritative fields from the extraction suggestion."""
    from app.modules.extraction.jd_extractor import JDDraft

    assert isinstance(draft, JDDraft)
    by_name = {f.name: f.value for f in draft.fields}
    if "position_title" in by_name:
        version.position_title = by_name["position_title"]
    if "department" in by_name:
        version.department = by_name["department"]
    if "location" in by_name:
        version.location = by_name["location"]
    if "work_mode" in by_name:
        version.work_mode = by_name["work_mode"]
    if "employment_type" in by_name:
        version.employment_type = by_name["employment_type"]
    if "number_of_openings" in by_name:
        with contextlib.suppress(ValueError):
            version.number_of_openings = int(by_name["number_of_openings"])
    if "minimum_total_experience_years" in by_name:
        with contextlib.suppress(ValueError):
            version.minimum_total_experience_years = float(
                by_name["minimum_total_experience_years"]
            )
