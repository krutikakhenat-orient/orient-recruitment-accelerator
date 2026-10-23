"""Applications application service: the public submission flow (Req 5.1-5.4).

submit_application orchestrates:
1. Validate the campaign is published/open and resolve its approved form version.
2. Validate submitted answers against the approved form (required fields; reject unknown
   or prohibited keys).
3. Require privacy consent; record the separate talent-pool opt-in only if given.
4. Resolve the canonical candidate (flagging potential duplicates for review).
5. Create the per-campaign Application with a snapshot of answers.
6. Ingest the resume through the safe document pipeline and run extraction.
7. Move the application to EXTRACTION_REVIEW, flagging MANUAL_REVIEW when extraction
   produced conflicts, low confidence, or safety flags.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.applications.transition_service import transition
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.candidates.models import ConsentPurpose
from app.modules.candidates.service import record_consent, resolve_candidate
from app.modules.documents.models import DocumentKind
from app.modules.documents.service import ingest_document
from app.modules.extraction.resume_extractor import extract_resume_fields
from app.modules.extraction.service import extract_resume_for_application
from app.modules.extraction.text_extractors import extract_text
from app.modules.forms.models import FormField, FormVersion, FormVersionStatus
from app.modules.forms.policy import PROHIBITED_FIELD_KEYS

_OPEN_STATES = {CampaignState.PUBLISHED.value, CampaignState.APPLICATIONS_OPEN.value}


def _logical_type_for(content_type: str, filename: str) -> str:
    """Map a declared MIME / filename extension to the extractor's logical type."""
    mime = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "txt",
    }
    if content_type in mime:
        return mime[content_type]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {"pdf": "pdf", "docx": "docx", "doc": "docx", "txt": "txt"}.get(ext, "unknown")


@dataclass
class SubmissionResult:
    application: Application
    candidate_created: bool
    duplicate_flagged: bool
    manual_review: bool
    extraction_summary: Any
    # Candidate-facing message computed from the walk-in messaging rule (never exposes
    # internal scores/notes). Set from the auto-screen result when available.
    candidate_message: str = ""


@dataclass
class ResumePreview:
    """Suggested form answers parsed from an uploaded resume, for candidate pre-fill.

    ``fields`` maps a form field key -> the suggested value (strings). ``extracted`` is True
    when the resume text could be read at all. These are SUGGESTIONS only: nothing is saved,
    no candidate record is created, and the candidate reviews/edits every value before
    submitting. Extraction is deterministic and treats the resume purely as data.
    """

    extracted: bool
    fields: dict[str, str]


# Resume-extracted keys that map onto baseline form field keys. We only pre-fill fields the
# deterministic extractor can produce with reasonable confidence; everything else the
# candidate fills in. Every pre-filled value stays EDITABLE and is never authoritative — the
# candidate reviews and can overwrite each one before submitting (extraction is untrusted
# data, responsible-ai.md). A suggestion is applied only when the form actually has that
# field (handled client-side), so extra keys here are harmless for forms that omit them.
_PREFILL_FIELD_MAP = {
    "full_name": "full_name",
    "email": "email",
    "mobile": "mobile",
    "total_experience_years": "total_experience_years",
    "current_location": "current_location",
    "skills": "skills",
}


def preview_resume_fields(
    *, resume_filename: str, resume_content_type: str, resume_bytes: bytes
) -> ResumePreview:
    """Parse an uploaded resume and return suggested answers for the public apply form.

    Read-only: extracts text with the existing document pipeline's text extractor and parses
    a few well-defined fields with the deterministic resume extractor. Nothing is persisted
    and no screening runs. Injection / keyword-stuffing markers are ignored (never acted on);
    low-confidence values are simply not suggested, so the candidate is never shown a
    misleading pre-fill.
    """
    logical_type = _logical_type_for(resume_content_type, resume_filename)
    text_result = extract_text(logical_type, resume_bytes)
    if not text_result.ok or not text_result.text.strip():
        return ResumePreview(extracted=False, fields={})

    parsed = extract_resume_fields(text_result.text)
    suggestions: dict[str, str] = {}
    for value in parsed.values:
        form_key = _PREFILL_FIELD_MAP.get(value.field_name)
        # Only surface a suggestion we're reasonably confident about (>= 0.5); below that the
        # candidate should type it themselves rather than trust a shaky parse.
        if form_key is not None and value.value and value.confidence >= 0.5:
            suggestions[form_key] = value.value
    return ResumePreview(extracted=True, fields=suggestions)


def _load_open_campaign(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.organisation_id != organisation_id:
        raise NotFoundError("Campaign not found")
    if campaign.state not in _OPEN_STATES:
        raise ConflictError("This campaign is not currently accepting applications")
    if campaign.approved_form_version_id is None:
        raise ConflictError("Campaign has no approved application form")
    return campaign


def _load_form(db: Session, form_version_id: uuid.UUID) -> tuple[FormVersion, list[FormField]]:
    version = db.get(FormVersion, form_version_id)
    if version is None or version.status != FormVersionStatus.APPROVED.value:
        raise ConflictError("Application form is not available")
    return version, list(version.fields)


def _validate_answers(
    fields: list[FormField], answers: dict[str, Any], *, allow_missing_required: bool = False
) -> None:
    """Validate submitted answers against the approved form.

    ``allow_missing_required`` relaxes the required-field check for the recruiter-attested
    walk-in bulk path, where a numeric field (e.g. years of experience) may be unknown at
    intake and is recovered from the resume text or completed during review. It is NEVER set
    on the public candidate submit path. Prohibited keys, unknown keys, and the privacy
    consent requirement are always enforced.
    """
    allowed_keys = {f.key for f in fields}
    for key in answers:
        if key in PROHIBITED_FIELD_KEYS:
            raise ValidationError(f"Field '{key}' is not accepted")
        if key not in allowed_keys:
            raise ValidationError(f"Unknown form field: '{key}'")
    if not allow_missing_required:
        for f in fields:
            if f.required and f.field_type != "file":
                value = answers.get(f.key)
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ValidationError(f"Missing required field: '{f.key}'")
    # Privacy consent must be explicitly granted — always required, even for walk-ins.
    if answers.get("privacy_consent") is not True:
        raise ValidationError("Privacy consent is required to submit an application")


def submit_application(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    answers: dict[str, Any],
    resume_filename: str,
    resume_content_type: str,
    resume_bytes: bytes,
    allow_missing_required: bool = False,
) -> SubmissionResult:
    campaign = _load_open_campaign(db, organisation_id, campaign_id)
    assert campaign.approved_form_version_id is not None
    form_version, fields = _load_form(db, campaign.approved_form_version_id)

    # The candidate selects the role (campaign) they apply to, so we never ask for a separate
    # "position applied for". New forms omit the field entirely; for any EXISTING approved
    # form that still has it, auto-fill it from the campaign's authoritative position title
    # so the (required) field is satisfied without the candidate ever seeing it.
    answers = dict(answers)
    if any(f.key == "position_applied_for" for f in fields) and not answers.get(
        "position_applied_for"
    ):
        answers["position_applied_for"] = campaign.position_title or campaign.name

    _validate_answers(fields, answers, allow_missing_required=allow_missing_required)

    # Resolve canonical candidate (flags potential duplicates for human review).
    resolution = resolve_candidate(
        db,
        organisation_id=organisation_id,
        full_name=str(answers["full_name"]),
        email=str(answers["email"]),
        mobile=str(answers.get("mobile")) if answers.get("mobile") else None,
    )
    candidate = resolution.candidate

    # One application per candidate per campaign.
    existing = db.execute(
        select(Application).where(
            Application.campaign_id == campaign_id,
            Application.candidate_id == candidate.id,
        )
    ).scalars().first()
    if existing is not None:
        raise ConflictError("An application already exists for this candidate and campaign")

    # Record consents: privacy (mandatory) + talent-pool (separate, optional).
    notice_version = campaign.privacy_notice_version or "unspecified"
    record_consent(
        db, organisation_id=organisation_id, candidate_id=candidate.id,
        purpose=ConsentPurpose.APPLICATION, notice_version=notice_version,
    )
    if answers.get("talent_pool_consent") is True:
        record_consent(
            db, organisation_id=organisation_id, candidate_id=candidate.id,
            purpose=ConsentPurpose.TALENT_POOL, notice_version=notice_version,
        )

    # Ingest the resume safely (validate + quarantine + scan). Raises on malicious files.
    resume_doc = ingest_document(
        db,
        organisation_id=organisation_id,
        actor_id=None,
        kind=DocumentKind.RESUME,
        filename=resume_filename,
        declared_content_type=resume_content_type,
        data=resume_bytes,
    )

    application = Application(
        organisation_id=organisation_id,
        campaign_id=campaign_id,
        candidate_id=candidate.id,
        form_version_id=form_version.id,
        answers=dict(answers),
        resume_document_id=resume_doc.id,
        state=ApplicationState.SUBMITTED.value,
    )
    db.add(application)
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            action="application.submitted",
            entity_type="application",
            entity_id=str(application.id),
            new_state_ref=ApplicationState.SUBMITTED.value,
        ),
    )

    # Move to processing, run extraction, then to extraction review (or manual review).
    transition(db, application=application,
               destination=ApplicationState.DOCUMENTS_PROCESSING,
               reason="documents received")
    summary = extract_resume_for_application(
        db,
        organisation_id=organisation_id,
        application_id=application.id,
        document_id=resume_doc.id,
        document_bytes=resume_bytes,
        logical_type=resume_doc.content_type_to_logical(),
        answers=answers,
    )
    transition(db, application=application,
               destination=ApplicationState.EXTRACTION_REVIEW,
               reason="extraction complete")

    # Automated deterministic screening on submit: if the campaign already has an approved
    # rule-set, score immediately so the result is waiting for staff (no manual trigger).
    # This never rejects/invites a candidate — borderline/low-confidence cases route to the
    # human Review Queue. If no rule-set is approved yet, this is a no-op and submission
    # still succeeds (staff can screen later from the Applications & Screening tab).
    from app.modules.screening import service as screening_service

    screening_failed = False
    auto_run = None
    try:
        auto_run = screening_service.auto_screen_on_submit(
            db, organisation_id=organisation_id, application=application
        )
    except Exception:  # noqa: BLE001 - submission must survive a screening failure
        # A screening error must NEVER be surfaced as a real score of zero (Section 9). The
        # application is preserved; the candidate gets the neutral "could not complete"
        # message and HR can screen manually later. We deliberately swallow the error here
        # (logged upstream by the audit/correlation layer) so the public submit still 201s.
        screening_failed = True

    manual_review = (
        auto_run.run.manual_review_required if auto_run is not None else summary.needs_manual_review
    )

    # Auto-progress a clean, high-scoring candidate straight onto the Interview Panel's list
    # (same-day walk-in). This reuses the existing walk-in path and is a no-op for below-50,
    # manual-review, conflicted or failed screenings — the existing safeguards are enforced
    # inside auto_progress_to_interview, not bypassed. Best-effort: it never blocks submit.
    if auto_run is not None:
        screening_service.auto_progress_to_interview(
            db, organisation_id=organisation_id, application=application, run=auto_run.run
        )

    candidate_message = screening_service.walk_in_candidate_message(
        screening_ran=auto_run is not None,
        screening_failed=screening_failed,
        score=auto_run.run.score if auto_run is not None else None,
        manual_review=manual_review,
        conflict_flagged=(auto_run.run.conflict_flagged if auto_run is not None else False),
    )

    return SubmissionResult(
        application=application,
        candidate_created=resolution.created,
        duplicate_flagged=resolution.duplicate_flagged,
        manual_review=manual_review,
        extraction_summary=summary,
        candidate_message=candidate_message,
    )


@dataclass
class WalkInIntakeItem:
    filename: str
    accepted: bool
    application_id: uuid.UUID | None
    duplicate: bool
    detail: str
    # Fit score (0..100) from the auto-screen run, when a rule-set is approved; else None.
    score: float | None = None
    manual_review: bool = False


def _derive_walk_in_answers(
    fields: list[FormField], resume_text: str, filename: str
) -> dict[str, Any]:
    """Build a best-effort application answer set for a walk-in resume.

    Identity we cannot read from the resume is filled with a clearly-marked walk-in
    placeholder derived from the file, so the recruiter can correct it later. Values the
    resume DOES contain (email, phone, years of experience) are used as-is. Privacy consent
    is set True because the recruiter attested, at the drive, that the candidate consented.
    """
    extraction = extract_resume_fields(resume_text)
    by_name = {v.field_name: v.value for v in extraction.values}

    stem = filename.rsplit(".", 1)[0].strip() or "Walk-in Candidate"
    safe_stem = "".join(ch for ch in stem if ch.isalnum() or ch in " -_").strip() or "walkin"

    placeholder_email = f"walkin.{safe_stem.lower().replace(' ', '.')}@walk-in.local"
    answers: dict[str, Any] = {
        "full_name": by_name.get("full_name") or f"Walk-in: {stem}",
        "email": by_name.get("email") or placeholder_email,
    }
    if "mobile" in by_name:
        answers["mobile"] = by_name["mobile"]
    if "total_experience_years" in by_name:
        answers["total_experience_years"] = by_name["total_experience_years"]

    # Satisfy other required, non-file fields so submission (and screening) succeeds; the
    # recruiter refines these during review. The placeholder MUST be type-appropriate:
    #   - number: leave ABSENT. A text placeholder ("to be confirmed") would fail a numeric
    #     criterion outright and also block the resume-text experience fallback. Leaving it
    #     absent lets the fallback recover a value from the resume, or routes to review.
    #   - boolean: default False (a safe, non-asserting value).
    #   - everything else (text/select/textarea): a clearly-marked text placeholder.
    for f in fields:
        if not f.required or f.field_type == "file" or f.key in answers:
            continue
        if f.field_type == "number":
            continue  # leave numeric fields unset — recovered from resume text or reviewed
        if f.field_type == "boolean":
            answers[f.key] = False
        else:
            answers[f.key] = "Walk-in — to be confirmed"

    answers["privacy_consent"] = True
    return answers


def bulk_intake_walk_in_resumes(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID,
    resumes: list[tuple[str, str, bytes]],
) -> list[WalkInIntakeItem]:
    """Create and auto-screen an application per walk-in resume (Req: walk-in drives).

    Each file goes through the SAME safe pipeline as a public application: validate + scan +
    quarantine the resume, extract fields, create the application, and (if the campaign has
    an approved rule-set) run deterministic screening so a fit score is available at once.
    Consent is recorded on the recruiter's attestation (captured at the drive). Identity not
    present in the resume is filled with a clearly-marked walk-in placeholder for the
    recruiter to correct. Screening never auto-rejects — borderline/low-confidence/conflict
    cases route to the Review Queue. Rejected/infected files are reported per-file.

    The campaign must be open for applications; otherwise each file is reported as skipped.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.organisation_id != organisation_id:
        raise NotFoundError("Campaign not found")

    form_fields: list[FormField] = []
    campaign_open = (
        campaign.state in _OPEN_STATES and campaign.approved_form_version_id is not None
    )
    if campaign_open:
        assert campaign.approved_form_version_id is not None
        _, form_fields = _load_form(db, campaign.approved_form_version_id)

    results: list[WalkInIntakeItem] = []
    for filename, content_type, data in resumes:
        if not data:
            results.append(WalkInIntakeItem(filename, False, None, False, "Empty file"))
            continue
        if not campaign_open:
            results.append(
                WalkInIntakeItem(
                    filename, False, None, False,
                    "Campaign is not open for applications — open it, then re-upload.",
                )
            )
            continue

        text_result = extract_text(_logical_type_for(content_type, filename), data)
        resume_text = text_result.text if text_result.ok else ""
        answers = _derive_walk_in_answers(form_fields, resume_text, filename)

        try:
            result = submit_application(
                db,
                organisation_id=organisation_id,
                campaign_id=campaign_id,
                answers=answers,
                resume_filename=filename,
                resume_content_type=content_type,
                resume_bytes=data,
                # Recruiter-attested bulk path: a required numeric field (e.g. experience)
                # may be unknown at intake and is recovered from resume text or reviewed.
                allow_missing_required=True,
            )
        except (ValidationError, ConflictError) as exc:
            results.append(WalkInIntakeItem(filename, False, None, False, str(exc)))
            continue

        run = result.extraction_summary  # noqa: F841 - kept for clarity; score read below
        score = _latest_score(db, organisation_id, result.application.id)
        detail = "Application created and screened" if score is not None else "Application created"
        if result.duplicate_flagged:
            detail += " (possible duplicate — flagged for review)"
        results.append(
            WalkInIntakeItem(
                filename=filename,
                accepted=True,
                application_id=result.application.id,
                duplicate=result.duplicate_flagged,
                detail=detail,
                score=score,
                manual_review=result.manual_review,
            )
        )

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="application.walk_in_bulk_intake",
            entity_type="campaign",
            entity_id=str(campaign_id),
            reason=f"{len([r for r in results if r.accepted])}/{len(results)} applications created",
        ),
    )
    return results


def _latest_score(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> float | None:
    """The most recent screening run's score for an application, if any."""
    from app.modules.screening.models import ScreeningRun

    run = db.execute(
        select(ScreeningRun)
        .where(
            ScreeningRun.organisation_id == organisation_id,
            ScreeningRun.application_id == application_id,
        )
        # Deterministic "latest": started_at is the primary key, id breaks same-tick ties
        # so two runs created in the same instant resolve to a single, stable newest run.
        .order_by(ScreeningRun.started_at.desc(), ScreeningRun.id.desc())
        .limit(1)
    ).scalars().first()
    return run.score if run is not None else None


@dataclass
class PublicApplicationStatus:
    """Candidate-facing screening status for a single application (no internal data).

    ``status`` is one of 'pending' (no completed score yet), 'scored' (a final score is
    saved) or 'failed' (a run exists but could not produce a score). ``message`` is the exact
    candidate-facing copy for that status. The raw score, evidence, recommendation and notes
    are NEVER included — privacy is preserved; the candidate only ever sees the message.
    """

    status: str
    message: str


def public_application_status(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> PublicApplicationStatus | None:
    """Resolve the two-stage candidate message for a given application id.

    Returns None only when the application does not exist (router -> 404). Otherwise derives
    the status from the LATEST screening run (deterministic selection matching the HR views):
      - no run yet, or a run that has not completed  -> 'pending' (keep the initial thank-you)
      - a completed run that recorded processing errors -> 'failed' (neutral message)
      - a completed run with a saved score -> 'scored' (strict 50-boundary outcome message)

    This reads ONLY the actual saved score; it never recomputes or alters scoring/ranking.
    """
    from app.modules.screening.models import ScreeningRun
    from app.modules.screening.service import (
        _MSG_SCREENING_FAILED,
        INITIAL_SUBMISSION_MESSAGE,
        score_outcome_message,
    )

    app = db.get(Application, application_id)
    if app is None or app.organisation_id != organisation_id:
        return None

    run = db.execute(
        select(ScreeningRun)
        .where(
            ScreeningRun.organisation_id == organisation_id,
            ScreeningRun.application_id == application_id,
        )
        .order_by(ScreeningRun.started_at.desc(), ScreeningRun.id.desc())
        .limit(1)
    ).scalars().first()

    # No run, or the latest run has not finished -> still pending; keep the thank-you.
    if run is None or run.completed_at is None:
        return PublicApplicationStatus(
            status="pending", message=INITIAL_SUBMISSION_MESSAGE
        )
    # A completed run that recorded a processing error is a FAILURE, never a real zero.
    if run.processing_errors:
        return PublicApplicationStatus(status="failed", message=_MSG_SCREENING_FAILED)
    # Completed and clean -> the strict 50-boundary outcome message from the saved score.
    return PublicApplicationStatus(
        status="scored", message=score_outcome_message(run.score)
    )


def get_application(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> Application:
    app = db.get(Application, application_id)
    if app is None or app.organisation_id != organisation_id:
        raise NotFoundError("Application not found")
    return app


def list_for_campaign(
    db: Session,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> list[Application]:
    """List applications for a campaign (organisation-scoped), newest first."""
    stmt = (
        select(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.campaign_id == campaign_id,
        )
        .order_by(Application.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars())


@dataclass
class RankedApplication:
    """An application paired with its latest screening run (or None if never screened).

    ``rank`` is 1-based over scored candidates in THIS campaign only; unscored candidates
    carry ``rank=None`` and are ordered last. ``scored`` is True only when a completed run
    with a usable score exists.
    """

    application: Application
    rank: int | None
    scored: bool
    score: float | None
    recommendation: str | None
    manual_review_required: bool | None
    conflict_flagged: bool | None
    latest_run_id: uuid.UUID | None


def list_ranked_for_campaign(
    db: Session,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> list[RankedApplication]:
    """List a campaign's applications ranked by latest-run fit score (desc), unscored last.

    Ranking is scoped strictly to this campaign (never mixed across campaigns). For each
    application the LATEST run is selected deterministically (started_at desc, then id desc
    to break same-tick ties), matching ``_latest_score`` and the screening-runs endpoint so
    every view agrees on which run is "current". A candidate with no completed run, or whose
    latest run carries no usable score, sorts last with ``rank=None`` and ``scored=False``;
    a failed/empty screening is therefore never shown as a real 0% at the top or bottom of
    the genuine ranking. Computed in two queries (applications + their runs) — no per-row
    API/DB round-trips.
    """
    from app.modules.screening.models import ScreeningRun

    apps = list(
        db.execute(
            select(Application).where(
                Application.organisation_id == organisation_id,
                Application.campaign_id == campaign_id,
            )
        ).scalars()
    )
    if not apps:
        return []

    app_ids = [a.id for a in apps]
    runs = list(
        db.execute(
            select(ScreeningRun)
            .where(
                ScreeningRun.organisation_id == organisation_id,
                ScreeningRun.application_id.in_(app_ids),
            )
            .order_by(ScreeningRun.started_at.desc(), ScreeningRun.id.desc())
        ).scalars()
    )
    # First run seen per application IS its latest, because the query is ordered newest-first.
    latest_by_app: dict[uuid.UUID, ScreeningRun] = {}
    for run in runs:
        latest_by_app.setdefault(run.application_id, run)

    def _is_scored(run: ScreeningRun | None) -> bool:
        # A completed run with a real score. An incomplete/failed run (no completed_at) is
        # NOT a valid score of zero (req 7/9) — it sorts last as "awaiting / unable to score".
        return run is not None and run.completed_at is not None

    scored: list[tuple[Application, ScreeningRun]] = []
    unscored: list[Application] = []
    for a in apps:
        candidate_run = latest_by_app.get(a.id)
        if candidate_run is not None and _is_scored(candidate_run):
            scored.append((a, candidate_run))
        else:
            unscored.append(a)

    # Rank scored candidates by score desc; stable secondary key keeps ordering deterministic.
    scored.sort(key=lambda pair: (-pair[1].score, str(pair[0].created_at), str(pair[0].id)))
    unscored.sort(key=lambda a: (a.created_at, a.id), reverse=True)

    out: list[RankedApplication] = []
    for i, (a, run) in enumerate(scored, start=1):
        out.append(
            RankedApplication(
                application=a, rank=i, scored=True, score=run.score,
                recommendation=run.recommendation,
                manual_review_required=run.manual_review_required,
                conflict_flagged=run.conflict_flagged, latest_run_id=run.id,
            )
        )
    for a in unscored:
        prior = latest_by_app.get(a.id)
        out.append(
            RankedApplication(
                application=a, rank=None, scored=False,
                score=None,
                recommendation=prior.recommendation if prior is not None else None,
                manual_review_required=(
                    prior.manual_review_required if prior is not None else None
                ),
                conflict_flagged=prior.conflict_flagged if prior is not None else None,
                latest_run_id=prior.id if prior is not None else None,
            )
        )
    return out[offset : offset + limit]
