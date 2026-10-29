"""Canonical permission catalogue and default role -> permission bundles.

Permissions are fine-grained (Req 1.2). Roles are bundles of permissions. Object-level
authorisation (campaign/application scoping) is applied in addition to these grants.
"""

from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    PROJECT_CREATE = "project.create"
    CAMPAIGN_CREATE = "campaign.create"
    CAMPAIGN_EDIT = "campaign.edit"
    CAMPAIGN_APPROVE = "campaign.approve"
    CAMPAIGN_PUBLISH = "campaign.publish"
    CAMPAIGN_PAUSE = "campaign.pause"
    JD_UPLOAD = "jd.upload"
    JD_REVIEW = "jd.review"
    JD_APPROVE = "jd.approve"
    RULE_CREATE = "rule.create"
    RULE_APPROVE = "rule.approve"
    THRESHOLD_CHANGE = "threshold.change"
    CANDIDATE_VIEW = "candidate.view"
    # Unmasking a candidate's raw contact PII (email/phone/LinkedIn) is a distinct, more
    # sensitive grant than viewing a candidate profile. Every unmask is audited.
    CANDIDATE_VIEW_PII = "candidate.view_pii"
    CANDIDATE_EXPORT = "candidate.export"
    CANDIDATE_CORRECT = "candidate.correct"
    APPLICATION_REVIEW = "application.review"
    SCREENING_EXECUTE = "screening.execute"
    SCREENING_OVERRIDE = "screening.override"
    INTERVIEW_APPROVE = "interview.approve"
    INTERVIEW_SCHEDULE = "interview.schedule"
    # Manage interviewer assignments (which panel member interviews which campaign/stage).
    # This is an ADMINISTRATIVE grant only — it governs assignment metadata and does NOT
    # confer any candidate-content access (no candidate.view / resume / scores / scorecards).
    INTERVIEW_ASSIGN = "interview.assign"
    ASSESSMENT_SUBMIT = "assessment.submit"
    HIRING_DECISION_RECOMMEND = "hiring_decision.recommend"
    HIRING_DECISION_APPROVE = "hiring_decision.approve"
    WAITLIST_MANAGE = "waitlist.manage"
    TALENT_POOL_SEARCH = "talent_pool.search"
    AUDIT_VIEW = "audit.view"
    PRIVACY_REQUEST_MANAGE = "privacy_request.manage"
    USER_MANAGE = "user.manage"
    SYSTEM_CONFIGURE = "system.configure"


class RoleName(str, Enum):
    """Operational staff roles (simplified 3-tier model) plus governance/candidate roles.

    The OPERATIONAL roles a day-to-day user is assigned are (3-tier model):
      - RECRUITER: authors the hiring setup (campaign, JD, screening rules, thresholds,
        form) and runs screening/scheduling, but holds NO approval authority. The Recruiter
        proposes; someone else signs off.
      - RECRUITER_ADMIN: everything the Recruiter does PLUS the approval authorities AND the
        Hiring Manager's duties — approve JD, approve rules/thresholds, approve
        campaign/publish, review candidates, approve interviews, and the final hiring
        decision (Select/Reject/Hold). This is the single recruitment-governance role that
        signs off what a Recruiter authored. It deliberately does NOT hold system
        administration (user lifecycle / system config) — those stay on SYSTEM_ADMIN.
      - INTERVIEW_PANEL: evaluate assigned candidates, record attendance, submit feedback.

    Separation of duties: the creator of a rule-set/threshold cannot be its sole approver
    (enforced in the service layer). So in practice a Recruiter authors the rules and a
    *different* Recruiter Admin approves them — two different accounts satisfy four-eyes.

    The remaining roles are NON-operational and intentionally retained because core
    governance features depend on them (audit log, system administration, privacy,
    management dashboards, and the public candidate). They are never part of the operator
    role choice but must continue to exist for RBAC to function.
    """

    RECRUITER = "recruiter"
    RECRUITER_ADMIN = "recruiter_admin"
    INTERVIEW_PANEL = "interview_panel"
    # Governance / non-operational (retained — removing these breaks audit/admin/privacy).
    MANAGEMENT_VIEWER = "management_viewer"
    AUDIT_VIEWER = "audit_viewer"
    SYSTEM_ADMIN = "system_admin"
    CANDIDATE = "candidate"


# The operational roles a staff member is assigned in the 3-tier model.
OPERATIONAL_ROLES: tuple[RoleName, ...] = (
    RoleName.RECRUITER,
    RoleName.RECRUITER_ADMIN,
    RoleName.INTERVIEW_PANEL,
)


P = Permission

# Author-only permissions a Recruiter holds (no approvals). The Recruiter Admin bundle is
# this set PLUS the approval authorities, so an admin can approve what a recruiter authored.
_RECRUITER_AUTHORING: set[Permission] = {
    P.PROJECT_CREATE, P.CAMPAIGN_CREATE, P.CAMPAIGN_EDIT,
    P.JD_UPLOAD, P.JD_REVIEW,
    P.RULE_CREATE,
    P.CANDIDATE_VIEW, P.CANDIDATE_CORRECT,
    P.APPLICATION_REVIEW, P.SCREENING_EXECUTE,
    P.INTERVIEW_SCHEDULE,
    P.WAITLIST_MANAGE, P.TALENT_POOL_SEARCH,
}

# Approval / sign-off authorities layered on top of authoring to form Recruiter Admin.
_RECRUITER_ADMIN_APPROVALS: set[Permission] = {
    P.CAMPAIGN_APPROVE, P.CAMPAIGN_PUBLISH, P.CAMPAIGN_PAUSE,
    P.JD_APPROVE, P.RULE_APPROVE, P.THRESHOLD_CHANGE,
    P.CANDIDATE_VIEW_PII,
    P.INTERVIEW_APPROVE,
    # Recruiter Admin owns the campaign operationally, so it also manages that campaign's
    # interviewer panel assignments (object-level: only for campaigns it is assigned to).
    P.INTERVIEW_ASSIGN,
    P.HIRING_DECISION_RECOMMEND, P.HIRING_DECISION_APPROVE,
}

# Default bundles. Object-level scoping still applies on top of these.
DEFAULT_ROLE_PERMISSIONS: dict[RoleName, set[Permission]] = {
    # Author-only operator: sets up campaigns and authors JDs, screening rules, thresholds
    # and forms, runs screening and schedules interviews — but cannot approve its own work.
    RoleName.RECRUITER: set(_RECRUITER_AUTHORING),
    # Full operational authority: authoring PLUS all approvals PLUS the Hiring Manager's
    # duties (JD review/approve, candidate review, interview approval, hiring
    # recommend/approve). It does NOT hold system administration. Separation-of-duties for
    # rule/threshold APPROVAL is still enforced in the service layer (the creator cannot be
    # the sole approver), so a Recruiter authors and a *different* Recruiter Admin approves.
    RoleName.RECRUITER_ADMIN: _RECRUITER_AUTHORING | _RECRUITER_ADMIN_APPROVALS,
    # Interview Panel: evaluate assigned candidates and submit feedback only.
    RoleName.INTERVIEW_PANEL: {
        P.ASSESSMENT_SUBMIT,
    },
    RoleName.MANAGEMENT_VIEWER: set(),  # aggregated dashboards only; no candidate PII
    RoleName.AUDIT_VIEWER: {
        P.AUDIT_VIEW,
    },
    # System Admin manages users/system/privacy. It ALSO manages interviewer assignments
    # (assignment metadata only). It deliberately holds NO candidate-content permission
    # (no candidate.view / view_pii / export, no assessment.submit): managing who interviews
    # a job must never leak candidate profiles, resumes, scores, or scorecards.
    RoleName.SYSTEM_ADMIN: {
        P.USER_MANAGE, P.SYSTEM_CONFIGURE, P.PRIVACY_REQUEST_MANAGE,
        P.INTERVIEW_ASSIGN,
    },
    RoleName.CANDIDATE: set(),  # candidate rights are modelled separately, not via staff perms
}
