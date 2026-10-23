"""Extraction application service for resumes (Req 5.3).

Runs text extraction + resume field parsing on a clean resume document, persists each
field with provenance/confidence/verification state, and compares extracted values with
the candidate-entered answers to flag conflicts and low confidence. Returns a summary used
to decide whether the application needs human review.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document, DocumentStatus
from app.modules.extraction.models import ExtractedField, VerificationStatus
from app.modules.extraction.resume_extractor import extract_resume_fields, match_skills_detailed
from app.modules.extraction.text_extractors import extract_text

# Confidence at or below this routes a field to human review.
LOW_CONFIDENCE_THRESHOLD = 0.5


@dataclass
class ExtractionSummary:
    fields_extracted: int
    conflicts: list[str]
    low_confidence_fields: list[str]
    safety_flags: list[str]
    needs_manual_review: bool


def _get_clean_resume(db: Session, organisation_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.organisation_id != organisation_id:
        raise ValueError("Resume document not found")
    if doc.status != DocumentStatus.CLEAN.value:
        raise ValueError("Resume document is not clean/available for extraction")
    return doc


def _jd_skills_for_application(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> list[str]:
    """The mandatory + desirable skills from the campaign's approved JD version.

    Returns an empty list when there is no approved JD yet (skill matching is then a no-op).
    """
    from app.modules.applications.models import Application
    from app.modules.campaigns.models import Campaign
    from app.modules.job_descriptions.models import JDVersion

    app = db.get(Application, application_id)
    if app is None or app.organisation_id != organisation_id:
        return []
    campaign = db.get(Campaign, app.campaign_id)
    if campaign is None or campaign.approved_jd_version_id is None:
        return []
    jd = db.get(JDVersion, campaign.approved_jd_version_id)
    if jd is None:
        return []
    skills = list(jd.mandatory_skills or []) + list(jd.desirable_skills or [])
    # De-duplicate case-insensitively while preserving the first-seen display name.
    seen: set[str] = set()
    unique: list[str] = []
    for s in skills:
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(s.strip())
    return unique


def _compare(field_name: str, extracted: str, answers: dict[str, Any]) -> bool:
    """Return True if the extracted value conflicts with the candidate-entered answer."""
    entered = answers.get(field_name)
    if entered is None:
        return False
    return str(entered).strip().lower() != str(extracted).strip().lower()


def extract_resume_for_application(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    document_bytes: bytes,
    logical_type: str,
    answers: dict[str, Any],
) -> ExtractionSummary:
    _get_clean_resume(db, organisation_id, document_id)

    text_result = extract_text(logical_type, document_bytes)
    parsed = extract_resume_fields(text_result.text if text_result.ok else "")

    # Persist the full extracted resume text so staff can read the actual resume later in
    # the candidate scorecard. Stored as a VERIFIED field (confidence 1.0) so it is treated
    # as real content, never routed to review as "low confidence". The raw file itself stays
    # in quarantined object storage and is never rendered directly (document-safety.md).
    if text_result.ok and text_result.text.strip():
        db.add(
            ExtractedField(
                organisation_id=organisation_id,
                application_id=application_id,
                source_document_id=document_id,
                field_name="resume_text",
                extracted_value=text_result.text,
                source_page=None,
                source_span=None,
                extraction_method=text_result.method,
                confidence=1.0,
                status=VerificationStatus.VERIFIED.value,
            )
        )

    # JD-driven skill matching: check the resume text for each skill named on the campaign's
    # approved JD, and persist one skill:<name> field per JD skill. Found skills are VERIFIED
    # evidence (so the exact_skill criteria can PASS); not-found skills are UNVERIFIED with a
    # routing confidence so an unconfirmed MANDATORY skill goes to human review, never an
    # auto-rejection (responsible-ai.md).
    jd_skills = _jd_skills_for_application(db, organisation_id, application_id)
    if jd_skills and text_result.ok:
        matches = match_skills_detailed(text_result.text, jd_skills)
        for skill_name, match in matches.items():
            db.add(
                ExtractedField(
                    organisation_id=organisation_id,
                    application_id=application_id,
                    source_document_id=document_id,
                    field_name=f"skill:{skill_name.strip().lower()}",
                    extracted_value="present" if match.present else "not_found",
                    source_page=None,
                    # Record the exact term that matched (JD spelling or declared alias) so
                    # an alias match such as "JS" for "JavaScript" stays explainable.
                    source_span=match.matched_term if match.present else None,
                    extraction_method=text_result.method,
                    confidence=1.0 if match.present else 0.4,
                    status=(
                        VerificationStatus.VERIFIED.value
                        if match.present
                        else VerificationStatus.UNVERIFIED.value
                    ),
                )
            )

    conflicts: list[str] = []
    low_confidence: list[str] = []

    for value in parsed.values:
        is_conflict = _compare(value.field_name, value.value, answers)
        if is_conflict:
            conflicts.append(value.field_name)
        is_low = value.confidence <= LOW_CONFIDENCE_THRESHOLD
        if is_low:
            low_confidence.append(value.field_name)

        status = VerificationStatus.UNVERIFIED.value
        if is_conflict:
            status = VerificationStatus.CONFLICT.value

        db.add(
            ExtractedField(
                organisation_id=organisation_id,
                application_id=application_id,
                source_document_id=document_id,
                field_name=value.field_name,
                extracted_value=value.value,
                source_page=None,
                source_span=value.source_span,
                extraction_method=text_result.method,
                confidence=value.confidence,
                status=status,
            )
        )
    db.flush()

    needs_review = bool(conflicts or low_confidence or parsed.flags or not text_result.ok)
    return ExtractionSummary(
        fields_extracted=len(parsed.values),
        conflicts=conflicts,
        low_confidence_fields=low_confidence,
        safety_flags=parsed.flags,
        needs_manual_review=needs_review,
    )


def list_fields(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> list[ExtractedField]:
    stmt = select(ExtractedField).where(
        ExtractedField.organisation_id == organisation_id,
        ExtractedField.application_id == application_id,
    )
    return list(db.execute(stmt).scalars())


def verify_field(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    field_id: uuid.UUID,
    actor_id: uuid.UUID,
    corrected_value: str | None = None,
    correction_reason: str | None = None,
) -> ExtractedField:
    """Confirm or correct an extracted field.

    The original ``extracted_value`` is NEVER overwritten (Req 9.1). Confirming sets the
    verified value to the extracted value; correcting records a new verified value plus a
    reason. Actor and timestamp are stamped for audit.
    """
    import datetime as dt

    from app.core.errors import NotFoundError, ValidationError

    field = db.get(ExtractedField, field_id)
    if field is None or field.organisation_id != organisation_id:
        raise NotFoundError("Extracted field not found")

    if corrected_value is not None:
        if not correction_reason or not correction_reason.strip():
            raise ValidationError("A correction reason is required when changing a value")
        field.verified_value = corrected_value
        field.correction_reason = correction_reason
        field.status = VerificationStatus.CORRECTED.value
    else:
        # Confirm the extracted value as-is.
        field.verified_value = field.extracted_value
        field.status = VerificationStatus.VERIFIED.value

    field.verified_by = actor_id
    field.verified_at = dt.datetime.now(tz=dt.UTC)
    db.flush()
    return field
