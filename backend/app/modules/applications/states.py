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
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    ASSESSED = "assessed"
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
    # Attendance is recorded by the INTERVIEW PANEL (who hold assessment.submit and are
    # invited to the specific candidate, not assigned to the campaign) — hence
    # campaign_scoped=False, mirroring the ASSESSED transition. The panel confirms the
    # candidate showed up, then assesses them.
    AppTransition(S.INTERVIEW_SCHEDULED, S.ATTENDED, "attended", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    AppTransition(S.INTERVIEW_SCHEDULED, S.NO_SHOW, "no_show", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
    AppTransition(S.ATTENDED, S.ASSESSED, "assessed", P.ASSESSMENT_SUBMIT,
                  campaign_scoped=False),
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
