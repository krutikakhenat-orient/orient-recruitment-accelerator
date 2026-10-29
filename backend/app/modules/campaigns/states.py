"""Campaign lifecycle states and the transition table (Req 2.3).

The transition table is the single source of truth for which campaign state changes are
permitted. Every transition declares its required permission, whether it needs an explicit
approval, and whether it has candidate-communication impact. Any transition not present in
the table is rejected by the TransitionService.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.modules.identity.permissions import Permission


class CampaignState(str, Enum):
    DRAFT = "draft"
    JD_UPLOADED = "jd_uploaded"
    JD_REVIEW = "jd_review"
    CRITERIA_CONFIGURATION = "criteria_configuration"
    CRITERIA_REVIEW = "criteria_review"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    PUBLISHED = "published"
    APPLICATIONS_OPEN = "applications_open"
    APPLICATIONS_CLOSED = "applications_closed"
    SCREENING = "screening"
    HUMAN_REVIEW = "human_review"
    INTERVIEW_PLANNING = "interview_planning"
    INTERVIEWING = "interviewing"
    SELECTION_REVIEW = "selection_review"
    COMPLETED = "completed"
    CLOSED = "closed"
    ARCHIVED = "archived"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TransitionRule:
    source: CampaignState
    destination: CampaignState
    permission: Permission
    # A short, stable identifier for the transition (used in audit new_state_ref).
    name: str
    requires_approval: bool = False
    candidate_communication_impact: bool = False
    # Names of prerequisites the TransitionService must verify before allowing it.
    required: tuple[str, ...] = field(default_factory=tuple)


S = CampaignState
P = Permission

# The permitted transitions. Order is irrelevant; lookups are by (source, destination).
TRANSITIONS: tuple[TransitionRule, ...] = (
    TransitionRule(S.DRAFT, S.JD_UPLOADED, P.JD_UPLOAD, "jd_uploaded",
                   required=("validated_jd_document",)),
    TransitionRule(S.JD_UPLOADED, S.JD_REVIEW, P.JD_REVIEW, "jd_review",
                   required=("extracted_jd_draft",)),
    TransitionRule(S.JD_REVIEW, S.CRITERIA_CONFIGURATION, P.JD_APPROVE, "jd_approved",
                   requires_approval=True, required=("approved_jd_version",)),
    TransitionRule(S.CRITERIA_CONFIGURATION, S.CRITERIA_REVIEW, P.RULE_CREATE,
                   "criteria_drafted"),
    TransitionRule(S.CRITERIA_REVIEW, S.APPROVAL_PENDING, P.RULE_APPROVE, "criteria_approved",
                   requires_approval=True, required=("approved_rule_set_version",)),
    TransitionRule(S.APPROVAL_PENDING, S.APPROVED, P.CAMPAIGN_APPROVE, "campaign_approved",
                   requires_approval=True,
                   required=("approved_jd_version", "approved_rule_set_version",
                             "approved_form_version", "active_threshold_version",
                             "privacy_notice_version")),
    TransitionRule(S.APPROVED, S.PUBLISHED, P.CAMPAIGN_PUBLISH, "campaign_published",
                   requires_approval=True, candidate_communication_impact=True,
                   required=("approved_jd_version", "approved_rule_set_version",
                             "approved_form_version", "active_threshold_version",
                             "privacy_notice_version")),
    TransitionRule(S.PUBLISHED, S.APPLICATIONS_OPEN, P.CAMPAIGN_PUBLISH, "applications_opened",
                   candidate_communication_impact=True),
    TransitionRule(S.APPLICATIONS_OPEN, S.APPLICATIONS_CLOSED, P.CAMPAIGN_PAUSE,
                   "applications_closed", candidate_communication_impact=True),
    TransitionRule(S.APPLICATIONS_CLOSED, S.SCREENING, P.SCREENING_EXECUTE, "screening_started"),
    TransitionRule(S.SCREENING, S.HUMAN_REVIEW, P.APPLICATION_REVIEW, "human_review_started"),
    TransitionRule(S.HUMAN_REVIEW, S.INTERVIEW_PLANNING, P.INTERVIEW_APPROVE,
                   "interview_planning", requires_approval=True),
    TransitionRule(S.INTERVIEW_PLANNING, S.INTERVIEWING, P.INTERVIEW_SCHEDULE,
                   "interviewing_started"),
    TransitionRule(S.INTERVIEWING, S.SELECTION_REVIEW, P.ASSESSMENT_SUBMIT, "selection_review"),
    TransitionRule(S.SELECTION_REVIEW, S.COMPLETED, P.HIRING_DECISION_APPROVE,
                   "campaign_completed", requires_approval=True),
    TransitionRule(S.COMPLETED, S.CLOSED, P.CAMPAIGN_EDIT, "campaign_closed"),
    TransitionRule(S.CLOSED, S.ARCHIVED, P.CAMPAIGN_EDIT, "campaign_archived"),
    # Reopen a closed campaign. Only an authoriser who can publish/open a campaign may
    # reopen it, and reopening re-admits candidates so it carries candidate-communication
    # impact. ARCHIVED remains terminal (a deliberately final, retained-record state); to
    # reuse an archived role, create a new campaign. (Req 4: "unless an authorised user
    # reopens the campaign".)
    TransitionRule(S.CLOSED, S.APPLICATIONS_OPEN, P.CAMPAIGN_PUBLISH, "campaign_reopened",
                   candidate_communication_impact=True),
    # Pause / resume.
    TransitionRule(S.APPLICATIONS_OPEN, S.PAUSED, P.CAMPAIGN_PAUSE, "campaign_paused",
                   candidate_communication_impact=True),
    TransitionRule(S.PAUSED, S.APPLICATIONS_OPEN, P.CAMPAIGN_PAUSE, "campaign_resumed",
                   candidate_communication_impact=True),
    # Cancellation closes a campaign whose hiring is abandoned. It is permitted from the
    # early setup states AND from the live operational states (post-open), because a role
    # can be dropped at any point before completion (Req 3: "when hiring is finished or
    # cancelled"). Cancelling preserves every candidate, resume, score, interview and
    # assignment record; it only stops new applications and new recruitment actions. It is
    # NOT permitted from COMPLETED (use close) or from CLOSED/ARCHIVED (already terminal).
    TransitionRule(S.DRAFT, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled"),
    TransitionRule(S.JD_UPLOADED, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled"),
    TransitionRule(S.JD_REVIEW, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled"),
    TransitionRule(S.CRITERIA_CONFIGURATION, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled"),
    TransitionRule(S.CRITERIA_REVIEW, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled"),
    TransitionRule(S.APPROVAL_PENDING, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled"),
    TransitionRule(S.APPROVED, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.PUBLISHED, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.APPLICATIONS_OPEN, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.APPLICATIONS_CLOSED, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.PAUSED, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.SCREENING, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.HUMAN_REVIEW, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.INTERVIEW_PLANNING, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.INTERVIEWING, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
    TransitionRule(S.SELECTION_REVIEW, S.CANCELLED, P.CAMPAIGN_EDIT, "campaign_cancelled",
                   candidate_communication_impact=True),
)

_TRANSITION_INDEX: dict[tuple[CampaignState, CampaignState], TransitionRule] = {
    (t.source, t.destination): t for t in TRANSITIONS
}


def find_transition(
    source: CampaignState, destination: CampaignState
) -> TransitionRule | None:
    return _TRANSITION_INDEX.get((source, destination))


def allowed_destinations(source: CampaignState) -> list[CampaignState]:
    return [t.destination for t in TRANSITIONS if t.source == source]
