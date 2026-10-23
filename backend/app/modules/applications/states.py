"""Application / candidate-disposition states and transition table (Req 5.2, design.md).

Like the campaign lifecycle, application status changes go only through a single
transition service. Any transition not in this table is rejected. Disposition changes
that affect the candidate (e.g. recommend for interview, reject) record a reason and an
audit event; several require an explicit permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.modules.identity.permissions import Permission


class ApplicationState(str, Enum):
    SUBMITTED = "submitted"
    DOCUMENTS_PROCESSING = "documents_processing"
    EXTRACTION_REVIEW = "extraction_review"
    SCREENED = "screened"
    MANUAL_REVIEW = "manual_review"
    ADDITIONAL_INFO_REQUESTED = "additional_info_requested"
    INTERVIEW_RECOMMENDED = "interview_recommended"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    # Panel-driven interview-day lifecycle (Check In -> assess -> Check Out). CHECKED_IN
    # means the candidate physically arrived and the panel opened their assessment;
    # CHECKED_OUT means the interview is finished AFTER the assessment was submitted, and
    # is what makes a candidate appear as "interview attended/completed" in Recruiter Admin.
    CHECKED_IN = "checked_in"
    # ATTENDED / NO_SHOW are LEGACY attendance states retained for historical records that
    # pre-date the check-in/check-out flow. New interviews use CHECKED_IN instead of
    # ATTENDED; we never silently convert existing ATTENDED/NO_SHOW rows.
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    ASSESSED = "assessed"
    CHECKED_OUT = "checked_out"
    SELECTED = "selected"
    REJECTED = "rejected"
    HOLD = "hold"
    WAITLISTED = "waitlisted"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class AppTransition:
    source: ApplicationState
    destination: ApplicationState
    name: str
    permission: Permission | None  # None => performed by system/pipeline, not a user action
    candidate_communication_impact: bool = False
    # When True (default), the actor must hold ``permission`` AND be assigned to the
    # campaign (object-level authorisation for campaign authors/owners). When False, only
    # the global permission is required: used for actors invited to a specific candidate's
    # interview (interview panel members) who are deliberately NOT campaign assignees. The
    # state guard that gates the transition (e.g. ATTENDED) is what scopes them instead.
    campaign_scoped: bool = True


S = ApplicationState
P = Permission

TRANSITIONS: tuple[AppTransition, ...] = (
    AppTransition(S.SUBMITTED, S.DOCUMENTS_PROCESSING, "documents_processing", None),
    AppTransition(S.DOCUMENTS_PROCESSING, S.EXTRACTION_REVIEW, "extraction_ready", None),
    AppTransition(S.EXTRACTION_REVIEW, S.SCREENED, "screened", P.SCREENING_EXECUTE),
    AppTransition(S.SCREENED, S.MANUAL_REVIEW, "to_manual_review", P.APPLICATION_REVIEW),
    AppTransition(S.MANUAL_REVIEW, S.SCREENED, "review_resolved", P.APPLICATION_REVIEW),
    AppTransition(S.MANUAL_REVIEW, S.ADDITIONAL_INFO_REQUESTED, "request_info",
                  P.APPLICATION_REVIEW, candidate_communication_impact=True),
    AppTransition(S.ADDITIONAL_INFO_REQUESTED, S.DOCUMENTS_PROCESSING, "info_resubmitted",
                  None),
    AppTransition(S.SCREENED, S.INTERVIEW_RECOMMENDED, "recommend_interview",
                  P.INTERVIEW_APPROVE),
    # A candidate under human review can also be selected for interview by an approver.
    AppTransition(S.MANUAL_REVIEW, S.INTERVIEW_RECOMMENDED, "recommend_interview",
                  P.INTERVIEW_APPROVE),
    AppTransition(S.SCREENED, S.WAITLISTED, "waitlist", P.WAITLIST_MANAGE),
    AppTransition(S.MANUAL_REVIEW, S.WAITLISTED, "waitlist", P.WAITLIST_MANAGE),
    AppTransition(S.INTERVIEW_RECOMMENDED, S.INTERVIEW_SCHEDULED, "schedule",
                  P.INTERVIEW_SCHEDULE, candidate_communication_impact=True),
    # --- Interview-day lifecycle, driven by the INTERVIEW PANEL ---
    # The panel holds assessment.submit and is invited to the specific candidate rather than
    # assigned to the campaign, so these are campaign_scoped=False; the source-state guard is
    # what scopes them (e.g. you can only check in a genuinely INTERVIEW_SCHEDULED candidate).
    #
    # 1. Check In: the candidate arrived and the panel opened their assessment. This does NOT
    #    mark the interview complete — only that it started.
    AppTransition(S.INTERVIEW_SCHEDULED, S.CHECKED_IN, "check_in", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    # 2. Assessment submitted: CHECKED_IN -> ASSESSED. A checked-in candidate must still be
    #    assessed before the interview can be closed.
    AppTransition(S.CHECKED_IN, S.ASSESSED, "assessed", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    # 3. Check Out: ASSESSED -> CHECKED_OUT. Separate event from assessment; only an assessed
    #    candidate can be checked out, so assessment-before-checkout is enforced by this guard.
    #    CHECKED_OUT is the state Recruiter Admin reads as "interview attended/completed".
    AppTransition(S.ASSESSED, S.CHECKED_OUT, "check_out", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    # --- LEGACY attendance path (retained for historical records; not used by new UI) ---
    # Older interviews recorded attendance directly as ATTENDED / NO_SHOW. These transitions
    # remain valid so pre-existing records keep working and remain reproducible. The legacy
    # ATTENDED -> ASSESSED edge is preserved too.
    AppTransition(S.INTERVIEW_SCHEDULED, S.ATTENDED, "attended", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    AppTransition(S.INTERVIEW_SCHEDULED, S.NO_SHOW, "no_show", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    AppTransition(S.ATTENDED, S.ASSESSED, "assessed", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    # Both the new CHECKED_OUT and the legacy ASSESSED lead to a hiring decision, so the
    # decision transitions accept either terminal interview state.
    AppTransition(S.CHECKED_OUT, S.SELECTED, "select", P.HIRING_DECISION_APPROVE,
                  candidate_communication_impact=True),
    AppTransition(S.CHECKED_OUT, S.REJECTED, "reject", P.HIRING_DECISION_APPROVE,
                  candidate_communication_impact=True),
    AppTransition(S.CHECKED_OUT, S.HOLD, "hold", P.HIRING_DECISION_RECOMMEND),
    AppTransition(S.ASSESSED, S.SELECTED, "select", P.HIRING_DECISION_APPROVE,
                  candidate_communication_impact=True),
    AppTransition(S.ASSESSED, S.REJECTED, "reject", P.HIRING_DECISION_APPROVE,
                  candidate_communication_impact=True),
    AppTransition(S.ASSESSED, S.HOLD, "hold", P.HIRING_DECISION_RECOMMEND),
    # Candidate-initiated withdrawal is allowed from most pre-decision states.
    AppTransition(S.SUBMITTED, S.WITHDRAWN, "withdraw", None,
                  candidate_communication_impact=True),
    AppTransition(S.EXTRACTION_REVIEW, S.WITHDRAWN, "withdraw", None,
                  candidate_communication_impact=True),
    AppTransition(S.SCREENED, S.WITHDRAWN, "withdraw", None,
                  candidate_communication_impact=True),
    AppTransition(S.MANUAL_REVIEW, S.WITHDRAWN, "withdraw", None,
                  candidate_communication_impact=True),
    AppTransition(S.INTERVIEW_RECOMMENDED, S.WITHDRAWN, "withdraw", None,
                  candidate_communication_impact=True),
    AppTransition(S.INTERVIEW_SCHEDULED, S.WITHDRAWN, "withdraw", None,
                  candidate_communication_impact=True),
)

_INDEX: dict[tuple[ApplicationState, ApplicationState], AppTransition] = {
    (t.source, t.destination): t for t in TRANSITIONS
}


def find_transition(
    source: ApplicationState, destination: ApplicationState
) -> AppTransition | None:
    return _INDEX.get((source, destination))


def allowed_destinations(source: ApplicationState) -> list[ApplicationState]:
    return [t.destination for t in TRANSITIONS if t.source == source]
