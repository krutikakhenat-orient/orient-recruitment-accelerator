"""Shared campaign report model (single source of truth).

Both the HR Excel export (``export_service.build_campaign_workbook_bytes``) and the in-app
JSON report preview (``reporting/router`` -> ``/campaigns/{id}/report``) are built from the
ONE structured report produced here, so the preview and the downloaded workbook always show
the same underlying candidate records.

Strictly READ-ONLY: it reuses ``application_service.list_ranked_for_campaign`` (the exact
ranking/scoring the UI uses) and joins the already-saved screening runs + criterion results.
Nothing is re-scored, inferred, or invented:

- The only candidate score that exists is ``ScreeningRun.score`` (0-100 fit percentage). We
  surface it as "Overall score".
- A "JD skills match %" is DERIVED transparently from the JD skill criteria only
  (``criterion_type == "exact_skill"``): awarded / max over those criteria. It is ``None``
  when the run has no skill criteria — never fabricated. It is a different number from the
  overall score and is always labelled as derived from JD skill criteria.
- "Relevant skills / strengths" and "missing / unverified requirements" are DERIVED from the
  saved ``CriterionResult`` rows using explicit, documented rules (see ``_derive_criteria``)
  — there are no stored fields for them. Outcome language is outcome-oriented, never
  "unfit"/"bad candidate" (product.md / responsible-ai.md).

Contact details: email/phone are MASKED by default. They are only unmasked when the caller
holds ``candidate.view_pii``; in that case each candidate is read through the audited
``candidates.service.reveal_contact`` so every PII access is logged (security.md).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.applications import service as application_service
from app.modules.applications.models import Application
from app.modules.campaigns.models import Campaign
from app.modules.candidates import service as candidate_service
from app.modules.candidates.models import Candidate
from app.modules.candidates.schemas import mask_email, mask_phone
from app.modules.documents.models import Document
from app.modules.job_descriptions.models import JDVersion
from app.modules.screening.models import CriterionResult

# Human-readable application statuses for HR (maps the raw ApplicationState enum values).
_STATUS_LABELS: dict[str, str] = {
    "submitted": "Submitted",
    "documents_processing": "Processing documents",
    "extraction_review": "Extraction review",
    "screened": "Screened",
    "manual_review": "In human review",
    "additional_info_requested": "Additional information requested",
    "interview_recommended": "Recommended for interview",
    "interview_scheduled": "Interview scheduled",
    "checked_in": "Interview in progress",
    "attended": "Interview attended",
    "no_show": "Did not attend",
    "assessed": "Assessed",
    "checked_out": "Interview completed",
    "selected": "Selected",
    "rejected": "Not selected",
    "hold": "On hold",
    "waitlisted": "Waitlisted",
    "withdrawn": "Withdrawn",
}

_TIER_LABELS: dict[str, str] = {
    "must_have": "Must-have",
    "good_to_have": "Good-to-have",
    "nice_to_have": "Nice-to-have",
}


def status_label(state: str) -> str:
    return _STATUS_LABELS.get(state, state.replace("_", " ").title())


@dataclass
class ReportColumn:
    """A column definition shared by the preview table and the Excel sheet."""

    key: str
    label: str
    width: int = 22


@dataclass
class CandidateReportRow:
    application_id: str
    candidate_name: str
    email: str | None
    phone: str | None
    contact_masked: bool
    applied_position: str
    status: str
    status_label: str
    scored: bool
    overall_score: float | None          # 0-100 fit %, the only stored score
    jd_skills_match: float | None        # derived from exact_skill criteria; None if none
    recommendation: str | None
    manual_review_required: bool
    conflict_flagged: bool
    relevant_skills: list[str]           # satisfied skill/requirement criterion names
    key_strengths: list[str]             # top satisfied criteria (by awarded points)
    missing_requirements: list[str]      # mandatory/must-have criteria not confirmed (fail)
    unverified_requirements: list[str]   # criteria routed to review (no decision yet)
    experience_summary: str | None
    education_summary: str | None
    resume_available: bool
    resume_filename: str | None
    rank: int | None


@dataclass
class CampaignReportSummary:
    campaign_id: str
    campaign_name: str
    position_title: str
    jd_role: str | None
    status: str
    status_label: str
    number_of_openings: int
    total_candidates: int
    scored_candidates: int
    unscored_candidates: int
    contact_unmasked: bool
    generated_at: str
    score_note: str


@dataclass
class CampaignReport:
    summary: CampaignReportSummary
    columns: list[ReportColumn] = field(default_factory=list)
    rows: list[CandidateReportRow] = field(default_factory=list)


# The HR-facing columns, in order. Shared by the preview and the Excel "Candidates" sheet so
# they never drift apart.
REPORT_COLUMNS: list[ReportColumn] = [
    ReportColumn("rank", "Rank", 7),
    ReportColumn("candidate_name", "Candidate name", 24),
    ReportColumn("email", "Email address", 30),
    ReportColumn("phone", "Contact number", 20),
    ReportColumn("applied_position", "Applied position", 26),
    ReportColumn("status_label", "Application status", 22),
    ReportColumn("overall_score", "Overall score (%)", 16),
    ReportColumn("jd_skills_match", "JD skills match (%)", 18),
    ReportColumn("relevant_skills", "Relevant skills & experience", 40),
    ReportColumn("key_strengths", "Key strengths", 36),
    ReportColumn("missing_requirements", "Missing / unverified requirements", 40),
    ReportColumn("resume", "Resume", 20),
    ReportColumn("summary_link", "Candidate summary", 22),
]


def _jd_role(db: Session, organisation_id: uuid.UUID, campaign: Campaign) -> str | None:
    if campaign.approved_jd_version_id is None:
        return None
    jd = db.get(JDVersion, campaign.approved_jd_version_id)
    if jd is None or jd.organisation_id != organisation_id:
        return None
    return jd.position_title


def _resume_filename(db: Session, organisation_id: uuid.UUID, app: Application) -> str | None:
    if app.resume_document_id is None:
        return None
    doc = db.get(Document, app.resume_document_id)
    if doc is None or doc.organisation_id != organisation_id:
        return None
    return doc.original_filename


def _candidate_name(app: Application, candidate: Candidate | None) -> str:
    answers = app.answers if isinstance(app.answers, dict) else {}
    name = answers.get("full_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if candidate is not None and candidate.full_name:
        return candidate.full_name
    return "Candidate"


def _answer_text(app: Application, *keys: str) -> str | None:
    """First non-empty string answer among ``keys`` (experience/education summaries)."""
    answers = app.answers if isinstance(app.answers, dict) else {}
    for k in keys:
        v = answers.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, int | float):
            return str(v)
    return None


def jd_skills_match(results: list[CriterionResult]) -> float | None:
    """Derived JD skills match %: awarded / max over the JD skill criteria only
    (``criterion_type == 'exact_skill'``). Returns None when the run scores no skill
    criteria — never fabricated, and distinct from the overall fit score."""
    skill = [c for c in results if c.criterion_type == "exact_skill"]
    total_max = sum(c.max_score for c in skill)
    if not skill or total_max <= 0:
        return None
    awarded = sum(c.awarded_score for c in skill)
    return round((awarded / total_max) * 100, 1)


def _derive_criteria(
    results: list[CriterionResult],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Derive HR-facing lists from saved criterion rows (no stored fields; documented rules):

    - relevant_skills: criteria the candidate satisfied (outcome == 'pass', awarded > 0).
    - key_strengths: the top satisfied criteria by awarded points (most decision-relevant).
    - missing_requirements: mandatory / must-have criteria NOT confirmed (outcome == 'fail').
      Worded as a requirement not confirmed — never "unfit" (responsible-ai.md).
    - unverified_requirements: criteria routed to human review (outcome == 'manual_review');
      missing evidence is not proof of absence, so these are "needs verification", not fails.
    """
    relevant: list[str] = []
    strengths: list[tuple[float, str]] = []
    missing: list[str] = []
    unverified: list[str] = []
    for c in results:
        outcome = (c.outcome or "").lower()
        if outcome == "pass" and c.awarded_score > 0:
            relevant.append(c.criterion_name)
            strengths.append((c.awarded_score, c.criterion_name))
        elif outcome == "fail" and (c.mandatory or c.tier == "must_have"):
            missing.append(c.criterion_name)
        elif outcome == "manual_review":
            unverified.append(c.criterion_name)
    strengths.sort(key=lambda t: (-t[0], t[1]))
    key_strengths = [name for _, name in strengths[:5]]
    return relevant, key_strengths, missing, unverified


def build_campaign_report(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign: Campaign,
    actor_id: uuid.UUID,
    unmask_contact: bool,
) -> CampaignReport:
    """Build the structured campaign report shared by the preview and the Excel export.

    Read-only with respect to scoring/persistence. When ``unmask_contact`` is True (the
    caller holds candidate.view_pii), each candidate's contact is read through the audited
    ``reveal_contact`` so every PII access is logged; otherwise contact stays masked.
    """
    apps = list(
        db.execute(
            select(Application).where(
                Application.organisation_id == organisation_id,
                Application.campaign_id == campaign.id,
            )
        ).scalars()
    )
    app_count = len(apps)
    ranked = application_service.list_ranked_for_campaign(
        db, organisation_id, campaign.id,
        limit=app_count if app_count > 0 else 1, offset=0,
    )

    # Resolve candidates once.
    candidate_by_id: dict[uuid.UUID, Candidate] = {}
    for r in ranked:
        cid = r.application.candidate_id
        if cid not in candidate_by_id:
            cand = db.get(Candidate, cid)
            if cand is not None and cand.organisation_id == organisation_id:
                candidate_by_id[cid] = cand

    # Preload the latest run + its criterion results for every ranked application.
    run_ids = [r.latest_run_id for r in ranked if r.latest_run_id is not None]
    results_by_run: dict[uuid.UUID, list[CriterionResult]] = {}
    if run_ids:
        for cr in db.execute(
            select(CriterionResult)
            .where(CriterionResult.screening_run_id.in_(run_ids))
            .order_by(CriterionResult.screening_run_id, CriterionResult.order_index)
        ).scalars():
            results_by_run.setdefault(cr.screening_run_id, []).append(cr)

    rows: list[CandidateReportRow] = []
    for r in ranked:
        app = r.application
        cand = candidate_by_id.get(app.candidate_id)
        results = results_by_run.get(r.latest_run_id, []) if r.latest_run_id else []
        relevant, strengths, missing, unverified = _derive_criteria(results)

        # Contact: masked by default; unmasked only via the audited reveal path.
        if unmask_contact and cand is not None:
            revealed = candidate_service.reveal_contact(
                db, organisation_id=organisation_id,
                candidate_id=cand.id, actor_id=actor_id,
            )
            email: str | None = revealed.email
            phone: str | None = revealed.mobile
            contact_masked = False
        else:
            email = mask_email(cand.email) if cand is not None else None
            phone = mask_phone(cand.mobile) if cand is not None else None
            contact_masked = True

        resume_name = _resume_filename(db, organisation_id, app)
        rows.append(
            CandidateReportRow(
                application_id=str(app.id),
                candidate_name=_candidate_name(app, cand),
                email=email,
                phone=phone,
                contact_masked=contact_masked,
                applied_position=campaign.position_title,
                status=app.state,
                status_label=status_label(app.state),
                scored=r.scored,
                overall_score=r.score,
                jd_skills_match=jd_skills_match(results),
                recommendation=r.recommendation,
                manual_review_required=bool(r.manual_review_required),
                conflict_flagged=bool(r.conflict_flagged),
                relevant_skills=relevant,
                key_strengths=strengths,
                missing_requirements=missing,
                unverified_requirements=unverified,
                experience_summary=_answer_text(
                    app, "total_experience_years", "experience", "years_experience"
                ),
                education_summary=_answer_text(app, "education", "highest_qualification"),
                resume_available=app.resume_document_id is not None,
                resume_filename=resume_name,
                rank=r.rank,
            )
        )

    scored_count = sum(1 for r in ranked if r.scored)
    summary = CampaignReportSummary(
        campaign_id=str(campaign.id),
        campaign_name=campaign.name,
        position_title=campaign.position_title,
        jd_role=_jd_role(db, organisation_id, campaign),
        status=campaign.state,
        status_label=status_label(campaign.state),
        number_of_openings=campaign.number_of_openings,
        total_candidates=app_count,
        scored_candidates=scored_count,
        unscored_candidates=app_count - scored_count,
        contact_unmasked=bool(unmask_contact),
        generated_at=dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        score_note=(
            "Overall score is the saved deterministic fit score (0-100%). "
            "JD skills match is derived from the job description's skill criteria only. "
            "Scores are human-reviewed and never auto-decide hiring."
        ),
    )
    return CampaignReport(summary=summary, columns=list(REPORT_COLUMNS), rows=rows)
