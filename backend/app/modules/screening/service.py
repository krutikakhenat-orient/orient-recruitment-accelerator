"""Screening orchestration service (Req 8.1-8.3; AC-08, AC-09, AC-10).

Pipeline: build evidence -> evaluate (deterministic engine) -> eligibility gates ->
weighted fit score -> confidence assessment -> recommendation. Produces an IMMUTABLE
ScreeningRun with all version pointers, an input hash and the engine version so the run
is reproducible. Uses ONLY the approved rule-set version and active threshold version
passed in (AC-08). Never auto-rejects: a sub-threshold or unconfirmed-mandatory result
yields an outcome status and (when caused by missing/low-confidence/conflicting evidence)
routes to human review (AC-10).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.modules.applications.models import Application
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.extraction.models import ExtractedField, VerificationStatus
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.rules.models import RuleSetVersion, ThresholdVersion
from app.modules.screening.models import (
    CriterionResult,
    EligibilityOutcome,
    ScreeningRecommendation,
    ScreeningRun,
)
from app.rules_engine.evaluator import (
    ENGINE_VERSION,
    CriterionOutcome,
    Evidence,
    EvidenceSet,
    Outcome,
    evaluate_node,
)


@dataclass
class ScreeningResult:
    run: ScreeningRun
    outcomes: list[CriterionOutcome]


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


# --- Candidate-facing walk-in messaging (business rule, Section 9) -------------------------
#
# This boundary (50%) is the agreed WALK-IN MESSAGING cutoff. It is DELIBERATELY SEPARATE
# from a JD's recommendation threshold (which drives the internal screening recommendation):
# the message a candidate sees at a drive is governed by this fixed 50% rule, while whether
# HR is advised to shortlist is governed by the campaign's own threshold version. The
# messages never expose internal scores, evidence or notes.
WALK_IN_MESSAGE_BOUNDARY = 50.0

_MSG_BELOW = (
    "Thank you for your application. Your CV has been received. The HR team will get back "
    "to you if there is a suitable next step."
)
_MSG_SELECTED = (
    "Your CV has been selected for the next stage. Kindly contact the HR department for "
    "your second round of interview."
)
_MSG_UNDER_REVIEW = (
    "Thank you for your application. Your details are being reviewed. Please wait for "
    "guidance from the HR team."
)
_MSG_SCREENING_FAILED = (
    "Your application has been received, but screening could not be completed right now. "
    "Please contact the HR team for assistance."
)
_MSG_RECEIVED = (
    "Your application has been received. Thank you. The HR team will review it and get back "
    "to you."
)


def walk_in_candidate_message(
    *,
    screening_ran: bool,
    screening_failed: bool,
    score: float | None,
    manual_review: bool,
    conflict_flagged: bool,
) -> str:
    """The exact candidate-facing message for the walk-in flow (Section 9).

    Deterministic and safe. Order of precedence:
      1. Screening/extraction failure -> neutral "could not be completed" message. A failed
         scoring operation is NEVER treated as a real score of zero.
      2. No screening yet (no approved rule-set) -> neutral "received" message. We never send
         a definitive score-based message before a screening result exists.
      3. Needs manual review / unresolved data conflict -> neutral "under review" message,
         even if the score is >= 50% (do not claim selection while a human still must look).
      4. Score >= 50% (and clean) -> "selected for next stage".
      5. Score < 50% -> polite "received, we'll be in touch".
    Internal scores/notes are never included in any branch.
    """
    if screening_failed:
        return _MSG_SCREENING_FAILED
    if not screening_ran or score is None:
        return _MSG_RECEIVED
    if manual_review or conflict_flagged:
        return _MSG_UNDER_REVIEW
    if score >= WALK_IN_MESSAGE_BOUNDARY:
        return _MSG_SELECTED
    return _MSG_BELOW


# --- Two-stage candidate screen messages (meeting requirement) ----------------------------
#
# Stage 1 is shown IMMEDIATELY after a successful submission, before any score exists.
# Stage 2 is shown ONLY after scoring has completed and the final score is saved, using the
# strict 50 boundary agreed in the meeting (below 50 vs 50-or-above). These reuse the exact
# approved copy above and never expose the raw score.
INITIAL_SUBMISSION_MESSAGE = "Thank you for applying. Your application has been received."

# The exact below-50 message the candidate sees on the public page (meeting-approved copy).
# Kept separate from `_MSG_BELOW` (used by the HR walk-in summary) so the candidate-facing
# wording can change without affecting the HR-side message.
_MSG_SCORE_BELOW = "THANK YOU FOR YOUR TIME HR WILL GET BACK TO YOU YOU CAN LEAVE FOR THE DAY"


def score_outcome_message(score: float) -> str:
    """The candidate-facing message for a COMPLETED score (meeting rule, strict 50 cutoff).

    Below 50 -> the agreed "thank you for your time" message. 50 or above -> "selected for
    the next stage". The caller must only use this once scoring is complete and the score is
    the actual value saved by the backend; pending/failed scoring is handled separately so an
    incorrect result is never shown.
    """
    if score >= WALK_IN_MESSAGE_BOUNDARY:
        return _MSG_SELECTED
    return _MSG_SCORE_BELOW


def build_evidence_set(answers: dict[str, Any], fields: list[ExtractedField]) -> EvidenceSet:
    """Assemble the normalised evidence the evaluator consumes.

    Candidate-entered answers are evidence at confidence 1.0 (self-reported). Verified or
    corrected extracted fields override/augment them with their recorded confidence.
    Unverified/conflicting extracted fields are included but keep their lower confidence,
    so the engine routes them to review per the rule's low_confidence behaviour.
    """
    evidence = EvidenceSet()
    for key, value in answers.items():
        evidence.fields[key] = Evidence(value=value, confidence=1.0, verified=False,
                                        source_ref="candidate_entered")

    for f in fields:
        # The stored full resume text is display-only; it is never a scoring criterion.
        if f.field_name == "resume_text":
            continue
        is_verified = f.status in {VerificationStatus.VERIFIED.value,
                                    VerificationStatus.CORRECTED.value}
        # JD skill matches (field "skill:<name>") feed the evaluator's verified_skills set so
        # exact_skill criteria can PASS. Only VERIFIED (found in the resume) skills count as
        # verified evidence; an unconfirmed mandatory skill routes to review, never a fail.
        if f.field_name.startswith("skill:"):
            skill_id = f.field_name.split(":", 1)[1]
            if is_verified:
                evidence.verified_skills.add(skill_id)
            continue
        value = f.effective_value
        confidence = 1.0 if is_verified else f.confidence
        evidence.fields[f.field_name] = Evidence(
            value=value, confidence=confidence, verified=is_verified,
            source_ref=f"extracted:{f.id}",
        )
    return evidence


# Extraction confidence at or above this is treated as adequately verified for the purpose
# of the self-assessment conflict check. Below it, a self-claim that relies on the field is
# flagged for a human (never auto-rejected).
SELF_ASSESSMENT_CONFIDENCE_FLOOR = 0.70


@dataclass(frozen=True)
class ConflictFinding:
    field_name: str
    claimed: str
    evidence: str
    reason: str


def _coerce_number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def detect_self_assessment_conflicts(
    answers: dict[str, Any], fields: list[ExtractedField]
) -> list[ConflictFinding]:
    """Deterministically compare candidate self-claims against extracted resume evidence.

    Flags two kinds of discrepancy, both of which route to HUMAN REVIEW and never cause an
    automatic rejection (responsible-ai.md: missing/weak evidence is not proof of absence):

    1. CLAIM EXCEEDS EVIDENCE: a numeric self-claim (e.g. years of experience) is materially
       greater than the corresponding verified resume value.
    2. LOW-CONFIDENCE BACKING: a GENUINE self-claim is only supported by an extracted field
       whose confidence is below SELF_ASSESSMENT_CONFIDENCE_FLOOR (0.70), so the claim
       cannot be considered verified.

    A value the system itself recovered from the resume text (the walk-in experience
    fallback, extraction_method="resume_text_fallback") is NOT a self-claim — it is the
    resume evidence — so it is never flagged as a conflict here. Its low confidence is
    already handled by the normal per-criterion low-confidence routing. This avoids a false
    "data conflict" on walk-in candidates whose experience was parsed from their resume.

    Pure and deterministic: identical inputs always yield identical findings.
    """
    by_name: dict[str, ExtractedField] = {}
    for f in fields:
        # Keep the highest-confidence field per name for a stable, deterministic comparison.
        existing = by_name.get(f.field_name)
        if existing is None or f.confidence > existing.confidence:
            by_name[f.field_name] = f

    findings: list[ConflictFinding] = []
    for key in sorted(answers):  # sorted => deterministic ordering
        field = by_name.get(key)
        if field is None:
            continue  # No resume evidence for this answer: absence is NOT a conflict.

        claimed_num = _coerce_number(answers[key])
        evidence_num = _coerce_number(field.effective_value)
        is_verified = field.status in {
            VerificationStatus.VERIFIED.value,
            VerificationStatus.CORRECTED.value,
        }
        # A value the SYSTEM recovered from the resume text (walk-in fallback) is not an
        # independent candidate self-claim — it IS the resume evidence. There is nothing to
        # "conflict" with, so it must not be flagged as a self-assessment conflict. Its low
        # confidence is already handled by the per-criterion low-confidence routing.
        system_recovered = field.extraction_method == "resume_text_fallback"

        # If the self-claim and the resume evidence AGREE, there is no conflict — regardless
        # of the extraction confidence. A numeric claim <= evidence is corroborated; a text
        # claim equal to the evidence (e.g. the candidate's own name that was also parsed
        # from the resume) is corroborated. Low extraction confidence on an AGREEING value is
        # not a discrepancy to flag — it is handled by per-criterion low-confidence routing.
        # This removes the spurious "data conflict" that previously fired on every candidate
        # (their name matched a 0.60-confidence extracted name) and blocked auto-progression.
        if claimed_num is not None and evidence_num is not None:
            if claimed_num > evidence_num:
                findings.append(
                    ConflictFinding(
                        field_name=key,
                        claimed=str(answers[key]),
                        evidence=str(field.effective_value),
                        reason=(
                            f"Claimed '{key}'={answers[key]} exceeds verified resume "
                            f"evidence ({field.effective_value})."
                        ),
                    )
                )
            # claimed_num <= evidence_num: corroborated, no conflict.
            continue

        # Non-numeric: a conflict only when the claim and the evidence genuinely DIFFER AND
        # the evidence is low-confidence/unverified. Equal (corroborating) values never
        # conflict. A placeholder/non-answer (e.g. a walk-in "to be confirmed") is not a
        # verifiable self-claim and is skipped.
        claimed_text = str(answers[key]).strip().lower()
        evidence_text = str(field.effective_value or "").strip().lower()
        if not claimed_text or _is_placeholder_answer(claimed_text):
            continue
        if claimed_text == evidence_text:
            continue  # claim corroborated by evidence
        if (
            not is_verified
            and not system_recovered
            and field.confidence < SELF_ASSESSMENT_CONFIDENCE_FLOOR
        ):
            findings.append(
                ConflictFinding(
                    field_name=key,
                    claimed=str(answers[key]),
                    evidence=str(field.effective_value),
                    reason=(
                        f"Self-claim for '{key}' differs from low-confidence resume "
                        f"evidence (confidence {field.confidence:.2f} < "
                        f"{SELF_ASSESSMENT_CONFIDENCE_FLOOR:.2f})."
                    ),
                )
            )
    return findings


# Placeholder / non-answer values a candidate (or walk-in intake) may leave in a field.
# These are not verifiable self-claims and must never be treated as a data conflict.
_PLACEHOLDER_ANSWERS: frozenset[str] = frozenset(
    {"walk-in - to be confirmed", "walk-in — to be confirmed", "to be confirmed", "tbc",
     "tbd", "n/a", "na", "not applicable", "none", "-", "--"}
)


def _is_placeholder_answer(text: str) -> bool:
    t = text.strip().lower()
    # Normalise dashes so "walk-in — to be confirmed" matches regardless of dash style.
    t = t.replace("—", "-").replace("–", "-")
    return t in _PLACEHOLDER_ANSWERS or "to be confirmed" in t


def _input_hash(answers: dict[str, Any], fields: list[ExtractedField],
                rules: list[dict[str, Any]], thresholds: tuple[float, float]) -> str:
    payload = json.dumps(
        {
            "answers": answers,
            "fields": sorted(
                [
                    {"name": f.field_name, "value": f.effective_value,
                     "status": f.status, "confidence": f.confidence}
                    for f in fields
                ],
                key=lambda d: d["name"],
            ),
            "rules": rules,
            "thresholds": list(thresholds),
        },
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_screening(
    db: Session,
    *,
    application: Application,
    rule_set_version: RuleSetVersion,
    threshold_version: ThresholdVersion | None,
    extracted_fields: list[ExtractedField],
) -> ScreeningResult:
    if not rule_set_version.is_approved:
        raise ValidationError("Screening requires an APPROVED rule-set version")
    if threshold_version is not None and not threshold_version.is_approved:
        raise ValidationError("Screening requires an APPROVED threshold version")

    review_below = threshold_version.review_below if threshold_version else 50.0
    recommend_at = threshold_version.recommend_at_or_above if threshold_version else 70.0

    evidence = build_evidence_set(application.answers, extracted_fields)

    # Evaluate every top-level rule; collect the flat leaf outcomes for the explainable score.
    all_outcomes: list[CriterionOutcome] = []
    for rule in rule_set_version.rules:
        _, leaves = evaluate_node(rule, evidence)
        all_outcomes.extend(leaves)

    # Eligibility gate: any mandatory criterion that is FAIL/REVIEW blocks "eligible".
    mandatory = [o for o in all_outcomes if o.mandatory]
    mandatory_failed = [o for o in mandatory if o.outcome is Outcome.FAIL]
    mandatory_review = [o for o in mandatory if o.outcome is Outcome.MANUAL_REVIEW]

    any_review = any(o.outcome is Outcome.MANUAL_REVIEW for o in all_outcomes)

    # Weighted fit score (0..100).
    #
    # The denominator is the weight of every criterion the candidate COULD earn points for —
    # i.e. every PASS/FAIL criterion PLUS any MANDATORY (must-have) criterion routed to
    # review. Rationale:
    #   - A must-have the resume did not confirm is still a core role requirement, so it
    #     belongs in the denominator: the fit % must read "demonstrated X% of the role",
    #     not silently drop the biggest requirements and inflate/colllapse the number. (It
    #     still routes the run to human review via the mandatory-review flag below, and is
    #     NEVER an automatic rejection — responsible-ai.md: missing != absent, route to a
    #     human.) Previously these were excluded from the denominator, which made the score
    #     be computed over only the leftover OPTIONAL skills — so a candidate who matched
    #     most must-haves but whose must-haves could not all be auto-confirmed scored a
    #     misleading 0-29%. Keeping them in the denominator gives an honest, intuitive fit %.
    #   - An OPTIONAL (good/nice-to-have) criterion routed to review (undecidable, non-
    #     mandatory) is excluded from BOTH numerator and denominator: an optional skill we
    #     genuinely could not assess should neither earn nor cost points. Optional skills the
    #     resume simply did not show are FAIL (in the denominator at 0) via the rule's
    #     missing_evidence="fail", so they correctly lower the % without routing to review.
    # The score stays deterministic: same evidence + rule version => same score.
    scored = [
        o
        for o in all_outcomes
        if o.outcome is not Outcome.MANUAL_REVIEW or o.mandatory
    ]
    total_max = sum(o.max_score for o in scored)
    total_awarded = sum(o.awarded_score for o in scored)

    # When NOTHING is decidable (every criterion routed to review — e.g. a JD that yields
    # only mandatory skills none of which could be matched, plus experience with no evidence),
    # there is no honest fit percentage. Persisting 0.0 would read as "worst possible fit"
    # when it actually means "we could not assess anything". In that case force the run to
    # human review with a no_decidable_evidence flag rather than a misleading real zero.
    no_decidable_evidence = total_max <= 0
    score = round((total_awarded / total_max) * 100, 2) if total_max > 0 else 0.0

    eligibility, confidence_status, recommendation, manual = _derive_outcome(
        mandatory_failed=mandatory_failed,
        mandatory_review=mandatory_review,
        any_review=any_review or no_decidable_evidence,
        score=score,
        review_below=review_below,
        recommend_at=recommend_at,
    )
    if no_decidable_evidence:
        # No PASS/FAIL criteria at all -> always a human decision, never an auto-outcome.
        manual = True
        confidence_status = "needs_review"
        recommendation = ScreeningRecommendation.ADDITIONAL_INFO_REQUIRED

    # Self-assessment conflict detection. A detected conflict ALWAYS routes to a human and
    # overrides the recommendation to DATA_CONFLICT, but it NEVER rejects the candidate.
    conflicts = detect_self_assessment_conflicts(application.answers, extracted_fields)
    conflict_detail: str | None = None
    if conflicts:
        manual = True
        recommendation = ScreeningRecommendation.DATA_CONFLICT
        confidence_status = "needs_review"
        conflict_detail = " ".join(c.reason for c in conflicts)

    input_hash = _input_hash(application.answers, extracted_fields, rule_set_version.rules,
                             (review_below, recommend_at))

    run = ScreeningRun(
        organisation_id=application.organisation_id,
        application_id=application.id,
        rule_set_version_id=rule_set_version.id,
        threshold_version_id=threshold_version.id if threshold_version else None,
        form_version_id=application.form_version_id,
        completed_at=_now(),
        score=score,
        eligibility_outcome=eligibility.value,
        confidence_status=confidence_status,
        recommendation=recommendation.value,
        manual_review_required=manual,
        conflict_flagged=bool(conflicts),
        conflict_detail=conflict_detail,
        input_data_hash=input_hash,
        engine_version=ENGINE_VERSION,
    )
    db.add(run)
    db.flush()

    for i, o in enumerate(all_outcomes):
        db.add(
            CriterionResult(
                screening_run_id=run.id,
                criterion_name=o.criterion_name,
                criterion_type=o.criterion_type,
                mandatory=o.mandatory,
                tier=o.tier,
                outcome=o.outcome.value,
                expected=_to_text(o.expected),
                candidate_evidence=_to_text(o.candidate_evidence),
                evidence_source=o.evidence_source,
                confidence=o.confidence,
                max_score=o.max_score,
                awarded_score=o.awarded_score,
                reason=o.reason,
                order_index=i,
            )
        )
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=application.organisation_id,
            action="screening.run_completed",
            entity_type="screening_run",
            entity_id=str(run.id),
            new_state_ref=recommendation.value,
            reason=f"score={score}; eligibility={eligibility.value}; hash={input_hash[:12]}",
        ),
    )
    return ScreeningResult(run=run, outcomes=all_outcomes)


def _derive_outcome(
    *,
    mandatory_failed: list[CriterionOutcome],
    mandatory_review: list[CriterionOutcome],
    any_review: bool,
    score: float,
    review_below: float,
    recommend_at: float,
) -> tuple[EligibilityOutcome, str, ScreeningRecommendation, bool]:
    # Missing/low-confidence/conflicting mandatory evidence -> review, never auto-reject.
    if mandatory_review:
        return (EligibilityOutcome.NEEDS_REVIEW, "needs_review",
                ScreeningRecommendation.ADDITIONAL_INFO_REQUIRED, True)
    if mandatory_failed:
        # Mandatory contradicted by confirmed evidence: outcome status, still HR-visible.
        return (EligibilityOutcome.NOT_CONFIRMED, "confirmed",
                ScreeningRecommendation.MANDATORY_NOT_CONFIRMED, False)

    confidence_status = "needs_review" if any_review else "confirmed"

    if any_review:
        return (EligibilityOutcome.NEEDS_REVIEW, confidence_status,
                ScreeningRecommendation.LOW_EXTRACTION_CONFIDENCE, True)

    if score >= recommend_at:
        return (EligibilityOutcome.ELIGIBLE, confidence_status,
                ScreeningRecommendation.RECOMMENDED_FOR_INTERVIEW_REVIEW, False)
    if score < review_below:
        return (EligibilityOutcome.ELIGIBLE, confidence_status,
                ScreeningRecommendation.WAITLIST_REVIEW, True)
    return (EligibilityOutcome.ELIGIBLE, confidence_status,
            ScreeningRecommendation.BORDERLINE_REVIEW, True)


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def execute_for_application(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    application: Application,
    rule_set_version: RuleSetVersion,
    threshold_version: ThresholdVersion | None,
    actor: AuthenticatedActor,
) -> ScreeningResult:
    """Load the application's extracted fields and run a screening, opening review items.

    This is a NEW run each time it is called (re-evaluation never overwrites prior runs,
    Req 11.2). Returns the immutable run plus its outcomes.

    Also advances the application's disposition: EXTRACTION_REVIEW -> SCREENED after a run,
    and SCREENED -> MANUAL_REVIEW when the run routes the candidate to a human. Both go
    through the application TransitionService (audited); re-runs on an already-screened
    application leave the state unchanged.
    """
    from sqlalchemy import select

    from app.modules.applications.states import ApplicationState
    from app.modules.applications.transition_service import transition as app_transition
    from app.modules.review.service import create_items_for_run

    # Refresh JD skill matches BEFORE screening so skill criteria score correctly even when
    # the rule-set/JD was approved AFTER the candidate applied. Extraction at submit time
    # may have had no JD skills to match; re-matching here against the stored resume text
    # keeps every run current without re-processing the raw file.
    _refresh_skill_matches(db, organisation_id, application, rule_set_version)
    # Fallback: if neither the candidate's answers nor structured extraction gave a years-of
    # -experience value, try to recover one from the raw resume text so the experience
    # criterion has something to evaluate instead of routing to review for a bare gap.
    _refresh_experience_years(db, organisation_id, application)

    fields = list(
        db.execute(
            select(ExtractedField).where(
                ExtractedField.organisation_id == organisation_id,
                ExtractedField.application_id == application.id,
            )
        ).scalars()
    )
    result = run_screening(
        db,
        application=application,
        rule_set_version=rule_set_version,
        threshold_version=threshold_version,
        extracted_fields=fields,
    )
    create_items_for_run(db, result.run)

    # Advance disposition so the candidate becomes actionable downstream (interview, etc.).
    if application.state == ApplicationState.EXTRACTION_REVIEW.value:
        app_transition(
            db, application=application, destination=ApplicationState.SCREENED,
            reason="screening run completed", actor=actor,
        )
    if (
        result.run.manual_review_required
        and application.state == ApplicationState.SCREENED.value
    ):
        app_transition(
            db, application=application, destination=ApplicationState.MANUAL_REVIEW,
            reason="screening routed to human review", actor=actor,
        )
    return result


def _rule_set_skill_terms(rule_set_version: RuleSetVersion | None) -> list[str]:
    """Collect the skill terms that the rule set actually scores (its exact_skill criteria),
    walking logical AND/OR/NOT groups. These are the skills evidence must be matched against
    so verified-skill evidence aligns 1:1 with the criteria — not whatever is stored on the
    JD (which may be stale/noisy relative to a regenerated rule set)."""
    terms: list[str] = []

    def _walk(node: dict[str, Any]) -> None:
        ctype = node.get("criterion_type")
        if ctype == "exact_skill":
            term = node.get("expected_value") or node.get("skill_id") or node.get("name")
            if term:
                terms.append(str(term))
        elif ctype in ("and", "or"):
            for child in node.get("children", []):
                if isinstance(child, dict):
                    _walk(child)
        elif ctype == "not":
            child = node.get("child")
            if isinstance(child, dict):
                _walk(child)

    if rule_set_version is not None:
        for rule in rule_set_version.rules or []:
            if isinstance(rule, dict):
                _walk(rule)
    return terms


def _refresh_skill_matches(
    db: Session,
    organisation_id: uuid.UUID,
    application: Application,
    rule_set_version: RuleSetVersion | None = None,
) -> None:
    """Re-match the campaign's JD skills against the candidate's stored resume text and
    upsert one skill:<name> field per JD skill. Idempotent: existing skill:* fields for the
    application are replaced so a run always reflects the current JD skill list. A match is a
    literal, case-insensitive, word-boundary search (no fuzzy inference, responsible-ai.md);
    a skill not found is recorded unverified so a mandatory skill routes to review, never a
    silent fail. No-op when there is no stored resume text or the JD lists no skills.
    """
    from sqlalchemy import select

    from app.modules.campaigns.models import Campaign
    from app.modules.extraction.resume_extractor import match_skills_detailed
    from app.modules.job_descriptions.models import JDVersion

    existing = list(
        db.execute(
            select(ExtractedField).where(
                ExtractedField.organisation_id == organisation_id,
                ExtractedField.application_id == application.id,
            )
        ).scalars()
    )
    resume_field = next((f for f in existing if f.field_name == "resume_text"), None)
    resume_text = (resume_field.effective_value or "") if resume_field else ""
    if not resume_text.strip():
        return

    # Match against the skills the RULE SET actually scores (its exact_skill criteria), not
    # whatever is stored on the JD. The JD's stored skill list can be stale or noisy relative
    # to a regenerated rule set (e.g. after a rescore that produced clean, gazetteer-derived
    # skills); matching the resume against the JD list would then build skill:* evidence that
    # does not line up with the criteria, so every criterion routes to review and the score
    # collapses. Deriving the skills from the rule set guarantees evidence aligns 1:1 with the
    # criteria being scored. Fall back to the JD's skills only when no rule set was supplied.
    jd_skills = _rule_set_skill_terms(rule_set_version)
    if not jd_skills:
        campaign = db.get(Campaign, application.campaign_id)
        if campaign is None or campaign.approved_jd_version_id is None:
            return
        jd = db.get(JDVersion, campaign.approved_jd_version_id)
        if jd is None:
            return
        jd_skills = list(jd.mandatory_skills or []) + list(jd.desirable_skills or [])
    if not jd_skills:
        return

    # Drop prior skill:* fields so the set exactly matches the current rule-set skills.
    for f in existing:
        if f.field_name.startswith("skill:"):
            db.delete(f)
    db.flush()

    source_doc_id = resume_field.source_document_id if resume_field else None
    method = resume_field.extraction_method if resume_field else "rematch"
    matches = match_skills_detailed(resume_text, jd_skills)
    for skill_name, match in matches.items():
        db.add(
            ExtractedField(
                organisation_id=organisation_id,
                application_id=application.id,
                source_document_id=source_doc_id,
                field_name=f"skill:{skill_name.strip().lower()}",
                extracted_value="present" if match.present else "not_found",
                source_page=None,
                # The exact term matched (JD spelling or declared alias), for explainability.
                source_span=match.matched_term if match.present else None,
                extraction_method=method,
                confidence=1.0 if match.present else 0.4,
                status=(
                    VerificationStatus.VERIFIED.value
                    if match.present
                    else VerificationStatus.UNVERIFIED.value
                ),
            )
        )
    db.flush()


def _refresh_experience_years(
    db: Session, organisation_id: uuid.UUID, application: Application
) -> None:
    """Recover a years-of-experience value from the raw resume text when nothing else has
    one.

    Fallback order of truth is preserved: the candidate's own answer (confidence 1.0 in the
    evidence set) and any structured ``total_experience_years`` extracted field take
    precedence — this ONLY fills a genuine gap. The recovered value is written UNVERIFIED
    with a routing confidence (0.4) so it is treated as advisory: a mandatory experience
    criterion backed only by this fallback routes to human review rather than scoring as
    confirmed (responsible-ai.md). No-op when a value already exists, there is no resume
    text, or the text contains no parseable experience figure. Idempotent.
    """
    from sqlalchemy import select

    from app.modules.extraction.resume_extractor import extract_resume_fields

    FIELD = "total_experience_years"

    # Candidate self-reported answer already covers it -> nothing to recover.
    answer = application.answers.get(FIELD)
    if answer not in (None, "") and _coerce_number(answer) is not None:
        return

    existing = list(
        db.execute(
            select(ExtractedField).where(
                ExtractedField.organisation_id == organisation_id,
                ExtractedField.application_id == application.id,
            )
        ).scalars()
    )
    # A structured extraction (or a prior fallback) already produced the field -> leave it.
    if any(f.field_name == FIELD for f in existing):
        return

    resume_field = next((f for f in existing if f.field_name == "resume_text"), None)
    resume_text = (resume_field.effective_value or "") if resume_field else ""
    if not resume_text.strip():
        return

    parsed = extract_resume_fields(resume_text)
    years = next((v for v in parsed.values if v.field_name == FIELD), None)
    if years is None:
        return

    db.add(
        ExtractedField(
            organisation_id=organisation_id,
            application_id=application.id,
            source_document_id=resume_field.source_document_id if resume_field else None,
            field_name=FIELD,
            extracted_value=years.value,
            source_page=None,
            source_span=years.source_span,
            extraction_method="resume_text_fallback",
            # Advisory: routes a mandatory experience criterion to review, never auto-passes.
            confidence=0.4,
            status=VerificationStatus.UNVERIFIED.value,
        )
    )
    db.flush()


def _system_actor(application: Application) -> AuthenticatedActor:
    """A system actor used only for automated screening on application submit.

    The candidate-facing submit flow is unauthenticated, so no human actor exists. Auto
    screening is a pipeline step performed by the system — it is granted exactly the two
    permissions the screening transitions need, scoped to this one campaign, and recorded
    in the audit trail as the system (actor email ``system.autoscreen``). It can never
    reject or invite a candidate; borderline/low-confidence cases still route to a human.
    """
    from app.modules.identity.permissions import Permission

    return AuthenticatedActor(
        user_id=application.created_by or application.candidate_id,
        organisation_id=application.organisation_id,
        email="system.autoscreen",
        role_names=["system_autoscreen"],
        permissions={
            Permission.SCREENING_EXECUTE.value,
            Permission.APPLICATION_REVIEW.value,
        },
        assigned_campaign_ids={application.campaign_id},
    )


def auto_screen_on_submit(
    db: Session, *, organisation_id: uuid.UUID, application: Application
) -> ScreeningResult | None:
    """Automatically screen a freshly-submitted application IF the campaign has an approved
    rule-set. Deterministic and safe: never auto-rejects/auto-invites; borderline or
    low-confidence results route to the human Review Queue. Returns None (a no-op) when no
    approved rule-set exists yet, so submission still succeeds."""
    from app.modules.rules import repository as rules_repo

    rule_version = rules_repo.latest_approved_rule_set_version(
        db, organisation_id, application.campaign_id
    )
    if rule_version is None:
        return None
    threshold_version = rules_repo.latest_approved_threshold_version(
        db, organisation_id, application.campaign_id
    )
    return execute_for_application(
        db,
        organisation_id=organisation_id,
        application=application,
        rule_set_version=rule_version,
        threshold_version=threshold_version,
        actor=_system_actor(application),
    )


@dataclass
class RescoreSummary:
    rescored: int
    criteria_count: int
    progressed: int = 0


def rescore_campaign(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor: AuthenticatedActor,
) -> RescoreSummary:
    """Repair affected candidates: regenerate the campaign's JD-derived criteria, then
    re-screen every application against them.

    This is the safe remediation for candidates stuck at 0/100 because the campaign's
    approved rule-set had no skill criteria (a stale manual starter set predating JD-based
    criteria). It:
      1. Regenerates + approves fresh JD-derived criteria (four-eyes preserved: system
         authors, the acting human approves). Raises ValidationError if the JD yields none.
      2. Re-screens each application as a NEW immutable run against the new rule-set and the
         active threshold. Prior runs are retained (reproducibility); stale review items are
         superseded by the new run (no duplicates). Candidate records and resumes are never
         modified.

    Nothing is reset or deleted. Returns how many applications were re-screened.
    """
    from sqlalchemy import select

    from app.modules.applications.models import Application
    from app.modules.rules import repository as rules_repo
    from app.modules.rules import service as rules_service

    new_version = rules_service.regenerate_criteria_from_jd(
        db, organisation_id=organisation_id, campaign_id=campaign_id,
        approver_id=actor.user_id,
    )
    threshold_version = rules_repo.latest_approved_threshold_version(
        db, organisation_id, campaign_id
    )

    apps = list(
        db.execute(
            select(Application).where(
                Application.organisation_id == organisation_id,
                Application.campaign_id == campaign_id,
            )
        ).scalars()
    )
    rescored = 0
    progressed = 0
    for application in apps:
        result = execute_for_application(
            db,
            organisation_id=organisation_id,
            application=application,
            rule_set_version=new_version,
            threshold_version=threshold_version,
            actor=_system_actor(application),
        )
        rescored += 1
        # Clean candidates scoring >= 50 go straight onto the Interview Panel's list (same
        # safeguards as submit-time auto-progression: not manual-review, not conflicted).
        # Below-50 / review candidates are left in the Review Queue.
        if auto_progress_to_interview(
            db, organisation_id=organisation_id, application=application, run=result.run
        ):
            progressed += 1

    return RescoreSummary(
        rescored=rescored, criteria_count=len(new_version.rules), progressed=progressed
    )


def _interview_system_actor(application: Application) -> AuthenticatedActor:
    """System actor for AUTO-PROGRESSING a clean, high-scoring candidate to the interview
    panel on submit. Granted exactly the two interview transition permissions (approve +
    schedule) scoped to this campaign, and recorded in the audit trail. It can only run the
    same walk-in path a recruiter would; the safeguards (score gate, manual-review/conflict
    checks) are enforced by the caller below, not bypassed."""
    from app.modules.identity.permissions import Permission

    return AuthenticatedActor(
        user_id=application.created_by or application.candidate_id,
        organisation_id=application.organisation_id,
        email="system.autoscreen",
        role_names=["system_autoscreen"],
        permissions={
            Permission.INTERVIEW_APPROVE.value,
            Permission.INTERVIEW_SCHEDULE.value,
        },
        assigned_campaign_ids={application.campaign_id},
    )


def auto_progress_to_interview(
    db: Session, *, organisation_id: uuid.UUID, application: Application, run: ScreeningRun
) -> bool:
    """Automatically place a clean, eligible candidate on the Interview Panel's list.

    Reuses the EXISTING walk-in path (`record_walk_in_interview`) so the candidate reaches
    INTERVIEW_SCHEDULED and appears on the panel exactly as a manual "Interview now (walk-in)"
    would — no new workflow, no time-slot assignment, no manual "Select for interview" click.

    Safeguards (never bypassed):
      - Score must be >= the agreed 50 boundary (below 50 is NOT auto-progressed).
      - No HARD blocker: a detected self-assessment conflict (conflict_flagged) or a
        mandatory criterion CONTRADICTED by confirmed evidence (recommendation
        mandatory_not_confirmed) keeps the candidate on the review path. These are genuine
        problems a human must resolve first.
      - Unconfirmed skills that merely ROUTED TO REVIEW do NOT block a candidate who already
        clears the score threshold: the interview panel verifies those skills anyway, so a
        strong candidate (e.g. 78%) with a couple of unverified skill keywords should reach
        the panel exactly as before — not be stranded in the review queue. (Previously the
        blanket manual_review_required gate stranded every high scorer whose resume did not
        literally contain every JD keyword.)
      - Idempotent: `record_walk_in_interview` reuses an existing invitation and
        `approve_invitation` blocks duplicates, so retries never create duplicate records.
      - The application must be in a state from which an interview can be recommended.
    Returns True when the candidate was progressed, False otherwise. Never raises: a failure
    here must not break submission (the candidate is simply left for manual handling).
    """
    from app.modules.applications.states import ApplicationState
    from app.modules.interviews.service import record_walk_in_interview

    if run.score < WALK_IN_MESSAGE_BOUNDARY:
        return False
    # Hard blockers only: a real data conflict, or a mandatory criterion contradicted by
    # confirmed evidence. Unconfirmed-but-not-contradicted skills (ADDITIONAL_INFO_REQUIRED)
    # do not block a candidate who already clears the score threshold.
    if run.conflict_flagged:
        return False
    if run.recommendation == ScreeningRecommendation.MANDATORY_NOT_CONFIRMED.value:
        return False
    if application.state not in {
        ApplicationState.SCREENED.value,
        ApplicationState.MANUAL_REVIEW.value,
        ApplicationState.INTERVIEW_RECOMMENDED.value,
    }:
        return False
    try:
        record_walk_in_interview(
            db, actor=_interview_system_actor(application), application=application
        )
        return True
    except Exception:  # noqa: BLE001 - progression is best-effort; never break submission
        return False
