"""Campaign application service.

Creating a campaign also assigns the creator to it so object-level authorisation works
immediately (the creator can act on the campaign they created). State changes are handled
exclusively by the TransitionService.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.campaigns import repository as repo
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.schemas import CampaignCreate
from app.modules.campaigns.states import CampaignState
from app.modules.identity.models import CampaignAssignment
from app.modules.projects import repository as project_repo


def create_campaign(
    db: Session,
    organisation_id: uuid.UUID,
    data: CampaignCreate,
    actor_id: uuid.UUID,
) -> Campaign:
    project = project_repo.get(db, organisation_id, data.project_id)
    if project is None:
        raise NotFoundError("Project not found")
    if (
        data.application_opening_date
        and data.application_closing_date
        and data.application_closing_date < data.application_opening_date
    ):
        raise ValidationError("Closing date cannot be before opening date")

    campaign = Campaign(
        organisation_id=organisation_id,
        project_id=data.project_id,
        name=data.name,
        position_title=data.position_title,
        campaign_type=data.campaign_type,
        number_of_openings=data.number_of_openings,
        employment_type=data.employment_type,
        work_location=data.work_location,
        work_mode=data.work_mode,
        application_opening_date=data.application_opening_date,
        application_closing_date=data.application_closing_date,
        state=CampaignState.DRAFT.value,
        recruiter_id=actor_id,
        created_by=actor_id,
        updated_by=actor_id,
    )
    campaign = repo.create(db, campaign)

    # Object-level authorisation: assign the creator to the new campaign.
    db.add(
        CampaignAssignment(
            user_id=actor_id, campaign_id=campaign.id, organisation_id=organisation_id
        )
    )
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="campaign.created",
            entity_type="campaign",
            entity_id=str(campaign.id),
            new_state_ref=CampaignState.DRAFT.value,
        ),
    )
    return campaign


def get_campaign(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = repo.get(db, organisation_id, campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found")
    return campaign


def delete_campaign(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign: Campaign,
    actor_id: uuid.UUID,
) -> int:
    """Hard-delete a campaign and every record scoped to it, in FK-safe order.

    This is a destructive, consequential action (it removes applications and their
    screening/review history). It is gated on campaign.edit + campaign assignment at the
    router, requires a typed confirmation in the UI, and emits an audit event recording how
    many applications were removed. We delete explicitly (not relying on DB cascades, which
    SQLite does not enforce by default) so no orphan rows are left behind.

    Returns the number of applications deleted (for the audit reason + UI feedback).
    """
    from app.modules.applications.models import Application
    from app.modules.assessments.models import Assessment
    from app.modules.decisions.models import HiringDecision
    from app.modules.extraction.models import ExtractedField
    from app.modules.forms.models import FormField, FormSchema, FormVersion
    from app.modules.identity.models import CampaignAssignment
    from app.modules.interviews.models import (
        InterviewInvitation,
        InterviewSlot,
        InterviewStage,
    )
    from app.modules.job_descriptions.models import JDVersion, JobDescription
    from app.modules.review.models import ReviewAction, ReviewItem
    from app.modules.rules.models import (
        RuleSet,
        RuleSetVersion,
        ThresholdSet,
        ThresholdVersion,
    )
    from app.modules.screening.models import CriterionResult, ScreeningRun
    from app.modules.waitlist.models import WaitlistRecord

    cid = campaign.id

    app_ids = [
        a.id
        for a in db.execute(
            select(Application).where(
                Application.organisation_id == organisation_id,
                Application.campaign_id == cid,
            )
        ).scalars()
    ]

    if app_ids:
        run_ids = [
            r.id
            for r in db.execute(
                select(ScreeningRun).where(ScreeningRun.application_id.in_(app_ids))
            ).scalars()
        ]
        item_ids = [
            i.id
            for i in db.execute(
                select(ReviewItem).where(ReviewItem.application_id.in_(app_ids))
            ).scalars()
        ]
        if run_ids:
            db.query(CriterionResult).filter(
                CriterionResult.screening_run_id.in_(run_ids)
            ).delete(synchronize_session=False)
        if item_ids:
            db.query(ReviewAction).filter(
                ReviewAction.review_item_id.in_(item_ids)
            ).delete(synchronize_session=False)
        db.query(ReviewItem).filter(ReviewItem.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        db.query(ScreeningRun).filter(ScreeningRun.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        db.query(ExtractedField).filter(ExtractedField.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        # Interview-day + downstream records scoped to these applications: assessments,
        # interview invitations, hiring decisions, waitlist entries. Removed so no orphan
        # rows remain after the applications are deleted.
        db.query(Assessment).filter(Assessment.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        db.query(InterviewInvitation).filter(
            InterviewInvitation.application_id.in_(app_ids)
        ).delete(synchronize_session=False)
        db.query(HiringDecision).filter(HiringDecision.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        db.query(WaitlistRecord).filter(WaitlistRecord.application_id.in_(app_ids)).delete(
            synchronize_session=False
        )
        db.query(Application).filter(Application.id.in_(app_ids)).delete(
            synchronize_session=False
        )

    # Interview stages/slots are campaign-scoped (not per-application). Delete slots first
    # (they reference a stage), then the stages.
    stage_ids = [
        s.id
        for s in db.execute(
            select(InterviewStage).where(
                InterviewStage.organisation_id == organisation_id,
                InterviewStage.campaign_id == cid,
            )
        ).scalars()
    ]
    if stage_ids:
        db.query(InterviewSlot).filter(InterviewSlot.stage_id.in_(stage_ids)).delete(
            synchronize_session=False
        )
        db.query(InterviewStage).filter(InterviewStage.id.in_(stage_ids)).delete(
            synchronize_session=False
        )

    # Campaign-scoped configuration (resolve child-version ids where a child table exists).
    form_schema_ids = [
        s.id
        for s in db.execute(
            select(FormSchema).where(FormSchema.campaign_id == cid)
        ).scalars()
    ]
    if form_schema_ids:
        fv_ids = [
            v.id
            for v in db.execute(
                select(FormVersion).where(FormVersion.form_schema_id.in_(form_schema_ids))
            ).scalars()
        ]
        if fv_ids:
            db.query(FormField).filter(FormField.form_version_id.in_(fv_ids)).delete(
                synchronize_session=False
            )
            db.query(FormVersion).filter(FormVersion.id.in_(fv_ids)).delete(
                synchronize_session=False
            )
        db.query(FormSchema).filter(FormSchema.id.in_(form_schema_ids)).delete(
            synchronize_session=False
        )

    rule_set_ids = [
        r.id
        for r in db.execute(select(RuleSet).where(RuleSet.campaign_id == cid)).scalars()
    ]
    if rule_set_ids:
        db.query(RuleSetVersion).filter(
            RuleSetVersion.rule_set_id.in_(rule_set_ids)
        ).delete(synchronize_session=False)
        db.query(RuleSet).filter(RuleSet.id.in_(rule_set_ids)).delete(
            synchronize_session=False
        )

    threshold_set_ids = [
        t.id
        for t in db.execute(
            select(ThresholdSet).where(ThresholdSet.campaign_id == cid)
        ).scalars()
    ]
    if threshold_set_ids:
        db.query(ThresholdVersion).filter(
            ThresholdVersion.threshold_set_id.in_(threshold_set_ids)
        ).delete(synchronize_session=False)
        db.query(ThresholdSet).filter(ThresholdSet.id.in_(threshold_set_ids)).delete(
            synchronize_session=False
        )

    jd_ids = [
        j.id
        for j in db.execute(
            select(JobDescription).where(JobDescription.campaign_id == cid)
        ).scalars()
    ]
    if jd_ids:
        db.query(JDVersion).filter(JDVersion.job_description_id.in_(jd_ids)).delete(
            synchronize_session=False
        )
        db.query(JobDescription).filter(JobDescription.id.in_(jd_ids)).delete(
            synchronize_session=False
        )

    db.query(CampaignAssignment).filter(CampaignAssignment.campaign_id == cid).delete(
        synchronize_session=False
    )

    # Emit the audit event BEFORE removing the campaign row (entity still resolvable).
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="campaign.deleted",
            entity_type="campaign",
            entity_id=str(cid),
            previous_state_ref=campaign.state,
            reason=(
                f"hard delete; removed {len(app_ids)} application(s) and all config, "
                "interviews, assessments, decisions and waitlist entries"
            ),
        ),
    )

    db.delete(campaign)
    db.flush()
    return len(app_ids)


# States in which a campaign is accepting candidate applications. Mirrors the applications
# service _OPEN_STATES so the public roles list only ever offers roles that can actually
# receive a submission.
PUBLIC_OPEN_STATES: tuple[str, ...] = (
    CampaignState.PUBLISHED.value,
    CampaignState.APPLICATIONS_OPEN.value,
)


def list_open_roles(db: Session, organisation_id: uuid.UUID) -> list[Campaign]:
    """Campaigns a candidate can apply to right now, for the consolidated public link.

    A role qualifies only when it is in an open state AND already has an approved
    application form — otherwise selecting it would immediately fail on submit. Ordered by
    position title for a stable dropdown. Organisation-scoped (single-org dev today, but the
    scope keeps multi-org isolation correct). Returns an empty list when nothing is open, so
    the public page can show an honest "no open positions" state rather than an error.
    """
    from sqlalchemy import select

    stmt = (
        select(Campaign)
        .where(
            Campaign.organisation_id == organisation_id,
            Campaign.state.in_(PUBLIC_OPEN_STATES),
            Campaign.approved_form_version_id.is_not(None),
        )
        .order_by(Campaign.position_title.asc())
    )
    return list(db.execute(stmt).scalars())


def assign_user(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign: Campaign,
    user_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """Assign a user to a campaign (object-level authorisation). Idempotent."""
    existing = (
        db.query(CampaignAssignment)
        .filter(
            CampaignAssignment.campaign_id == campaign.id,
            CampaignAssignment.user_id == user_id,
        )
        .one_or_none()
    )
    if existing is not None:
        return
    db.add(
        CampaignAssignment(
            user_id=user_id, campaign_id=campaign.id, organisation_id=organisation_id
        )
    )
    db.flush()
    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="campaign.user_assigned",
            entity_type="campaign",
            entity_id=str(campaign.id),
            reason=f"assigned user={user_id}",
        ),
    )


_FIVE_ARTIFACTS = (
    ("approved_jd_version_id", "approved JD"),
    ("approved_rule_set_version_id", "approved rule-set"),
    ("approved_form_version_id", "approved form"),
    ("active_threshold_version_id", "active threshold"),
    ("privacy_notice_version", "privacy notice"),
)

# Final governance gates, in order, collapsed into one fast-track action.
_FAST_TRACK_PATH = (
    CampaignState.APPROVAL_PENDING,
    CampaignState.APPROVED,
    CampaignState.PUBLISHED,
    CampaignState.APPLICATIONS_OPEN,
)


def fast_track_open(db: Session, *, actor, campaign: Campaign):  # type: ignore[no-untyped-def]
    """Collapse the final approval gates into one action: drive the campaign from its
    current state straight to APPLICATIONS_OPEN.

    This is a convenience, NOT a governance bypass: the five artifacts must already be
    approved (each via its own four-eyes/SoD flow), and every transition still runs through
    the TransitionService with its permission check and audit event. It only removes the
    click-by-click stepping through approval_pending -> approved -> published -> open.
    Requires campaign.approve + campaign.publish, which the HR Head role holds.
    """
    from app.modules.campaigns.transition_service import transition

    missing = [label for attr, label in _FIVE_ARTIFACTS if getattr(campaign, attr, None) is None]
    if missing:
        raise ValidationError(
            "Cannot fast-track: these artifacts are not approved yet: " + ", ".join(missing)
        )

    current = CampaignState(campaign.state)
    if current is CampaignState.APPLICATIONS_OPEN:
        return campaign
    try:
        start = _FAST_TRACK_PATH.index(current)
    except ValueError as exc:
        raise ValidationError(
            "Fast-track is only available once the campaign reaches 'approval pending' "
            f"(current state: {current.value})."
        ) from exc

    for destination in _FAST_TRACK_PATH[start + 1:]:
        transition(
            db, actor=actor, campaign=campaign, destination=destination,
            reason="fast-track open (artifacts pre-approved)",
        )
    return campaign


# --- Setup checklist + one-step "Open for applications" ---------------------------------
#
# HR thinks in four jobs to do (upload the JD, get it approved, approve the application
# form, open the job), not in the twelve internal lifecycle states. The checklist below is a
# read-only projection of the campaign's approved artifacts, and open_for_applications walks
# the remaining setup states for the user — every hop still goes through the
# TransitionService (permission + assignment check + audit event), so this is a
# convenience, never a governance bypass.

# The full setup path in order. open_for_applications walks forward from wherever the
# campaign currently is on this path.
_SETUP_PATH: tuple[CampaignState, ...] = (
    CampaignState.DRAFT,
    CampaignState.JD_UPLOADED,
    CampaignState.JD_REVIEW,
    CampaignState.CRITERIA_CONFIGURATION,
    CampaignState.CRITERIA_REVIEW,
    CampaignState.APPROVAL_PENDING,
    CampaignState.APPROVED,
    CampaignState.PUBLISHED,
    CampaignState.APPLICATIONS_OPEN,
)

# States before the job is visible to candidates.
_PRE_OPEN_STATES: frozenset[str] = frozenset(s.value for s in _SETUP_PATH[:-2])


class SetupStep:
    __slots__ = ("key", "title", "description", "status", "who")

    def __init__(self, key: str, title: str, description: str, status: str, who: str) -> None:
        self.key = key
        self.title = title
        self.description = description
        self.status = status
        self.who = who


class SetupStatus:
    __slots__ = (
        "campaign_id", "is_open", "next_step_key", "steps",
        "latest_jd_version_id", "latest_jd_status", "draft_form_version_id",
    )

    def __init__(
        self,
        *,
        campaign_id: uuid.UUID,
        is_open: bool,
        next_step_key: str | None,
        steps: list[SetupStep],
        latest_jd_version_id: uuid.UUID | None,
        latest_jd_status: str | None,
        draft_form_version_id: uuid.UUID | None,
    ) -> None:
        self.campaign_id = campaign_id
        self.is_open = is_open
        self.next_step_key = next_step_key
        self.steps = steps
        self.latest_jd_version_id = latest_jd_version_id
        self.latest_jd_status = latest_jd_status
        self.draft_form_version_id = draft_form_version_id


def setup_status(db: Session, *, campaign: Campaign) -> SetupStatus:
    """What is done and what to do next before this job can take applications (read-only).

    Steps 1-3 can be worked on in any order; "open" only becomes actionable once they are
    all done. ``next_step_key`` is the first step that is not done.
    """
    from app.modules.forms.models import FormSchema, FormVersion
    from app.modules.job_descriptions.models import JDVersion, JobDescription

    latest_jd = db.execute(
        select(JDVersion)
        .join(JobDescription, JDVersion.job_description_id == JobDescription.id)
        .where(
            JobDescription.organisation_id == campaign.organisation_id,
            JobDescription.campaign_id == campaign.id,
        )
        .order_by(JDVersion.created_at.desc(), JDVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()

    draft_form = db.execute(
        select(FormVersion)
        .join(FormSchema, FormVersion.form_schema_id == FormSchema.id)
        .where(
            FormSchema.organisation_id == campaign.organisation_id,
            FormSchema.campaign_id == campaign.id,
            FormVersion.status == "draft",
        )
        .order_by(FormVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()

    state = campaign.state
    is_open = state in (CampaignState.PUBLISHED.value, CampaignState.APPLICATIONS_OPEN.value)
    went_live = state not in _PRE_OPEN_STATES and state != CampaignState.CANCELLED.value

    jd_uploaded = latest_jd is not None or campaign.approved_jd_version_id is not None
    jd_approved = campaign.approved_jd_version_id is not None
    criteria_ready = (
        campaign.approved_rule_set_version_id is not None
        and campaign.active_threshold_version_id is not None
    )
    form_approved = campaign.approved_form_version_id is not None

    def _status(done: bool, waiting_on_approver: bool = False, blocked: bool = False) -> str:
        if done:
            return "done"
        if blocked:
            return "waiting"
        return "needs_approver" if waiting_on_approver else "todo"

    steps = [
        SetupStep(
            "upload_jd", "Upload the job description",
            "Upload the JD file (PDF or Word). The system reads it and pre-fills the details.",
            _status(jd_uploaded), "Recruiter",
        ),
        SetupStep(
            "approve_jd", "Check and approve the job description",
            "An approver checks the extracted details and approves them. Approving also "
            "creates the screening criteria automatically.",
            _status(jd_approved, waiting_on_approver=jd_uploaded, blocked=not jd_uploaded),
            "Recruiter Admin",
        ),
        SetupStep(
            "criteria", "Screening criteria ready",
            "Created automatically from the approved JD. You can review them later.",
            _status(criteria_ready, blocked=not jd_approved), "Automatic",
        ),
        SetupStep(
            "form", "Approve the application form",
            "Create the form candidates fill in, then approve it.",
            _status(form_approved, waiting_on_approver=draft_form is not None),
            "Recruiter, then Recruiter Admin",
        ),
        SetupStep(
            "open", "Open for applications",
            "Makes the job live and gives you the apply link to share with candidates.",
            _status(
                went_live,
                blocked=not (jd_approved and criteria_ready and form_approved),
            ),
            "Recruiter Admin",
        ),
    ]
    next_step = next((s.key for s in steps if s.status != "done"), None)
    return SetupStatus(
        campaign_id=campaign.id,
        is_open=is_open,
        next_step_key=next_step,
        steps=steps,
        latest_jd_version_id=latest_jd.id if latest_jd is not None else None,
        latest_jd_status=latest_jd.status if latest_jd is not None else None,
        draft_form_version_id=draft_form.id if draft_form is not None else None,
    )


def open_for_applications(db: Session, *, actor, campaign: Campaign) -> Campaign:  # type: ignore[no-untyped-def]
    """Open a fully set-up job for applications in one action.

    Preconditions are checked up front with plain-language errors that name the checklist
    step still missing. The actor must hold campaign.publish on this campaign (checked
    first, so a Recruiter gets a clear "needs an approver" error rather than a partial walk).
    If no privacy notice is attached yet, the organisation default is attached and audited —
    candidates consent against it. Then the campaign walks the remaining setup states via
    the TransitionService, which re-checks each hop's permission and records its audit event.
    """
    from app.core.config import get_settings
    from app.modules.campaigns.transition_service import transition
    from app.modules.identity.permissions import Permission
    from app.modules.identity.policy import require_campaign_permission

    require_campaign_permission(actor, Permission.CAMPAIGN_PUBLISH, campaign.id)

    current = CampaignState(campaign.state)
    if current is CampaignState.APPLICATIONS_OPEN:
        return campaign
    if current not in _SETUP_PATH:
        raise ValidationError(
            "This job is past setup (status: "
            f"{current.value.replace('_', ' ')}). Use the status controls under Settings "
            "to reopen or resume it."
        )

    missing: list[str] = []
    if campaign.approved_jd_version_id is None:
        missing.append("approve the job description (step 2)")
    elif (
        campaign.approved_rule_set_version_id is None
        or campaign.active_threshold_version_id is None
    ):
        missing.append("screening criteria are not ready (step 3)")
    if campaign.approved_form_version_id is None:
        missing.append("approve the application form (step 4)")
    if missing:
        raise ValidationError("Not ready to open yet: " + "; ".join(missing) + ".")

    if campaign.privacy_notice_version is None:
        notice = get_settings().default_privacy_notice_version
        campaign.privacy_notice_version = notice
        campaign.updated_by = actor.user_id
        db.flush()
        record_event(
            db,
            AuditEventWrite(
                organisation_id=campaign.organisation_id,
                actor_id=actor.user_id,
                action="campaign.privacy_notice_attached",
                entity_type="campaign",
                entity_id=str(campaign.id),
                reason=f"organisation default privacy notice {notice} attached on open",
            ),
        )

    start = _SETUP_PATH.index(current)
    for destination in _SETUP_PATH[start + 1:]:
        transition(
            db, actor=actor, campaign=campaign, destination=destination,
            reason="Opened for applications from the setup checklist",
        )
    return campaign


def set_approved_jd_version(
    db: Session, campaign: Campaign, jd_version_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    campaign.approved_jd_version_id = jd_version_id
    campaign.updated_by = actor_id
    db.flush()


def set_approved_form_version(
    db: Session, campaign: Campaign, form_version_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    campaign.approved_form_version_id = form_version_id
    campaign.updated_by = actor_id
    db.flush()


def configure_governance(
    db: Session,
    campaign: Campaign,
    *,
    actor_id: uuid.UUID,
    privacy_notice_version: str | None = None,
    retention_policy: str | None = None,
    active_threshold_version_id: uuid.UUID | None = None,
    approved_rule_set_version_id: uuid.UUID | None = None,
) -> None:
    if privacy_notice_version is not None:
        campaign.privacy_notice_version = privacy_notice_version
    if retention_policy is not None:
        campaign.retention_policy = retention_policy
    if active_threshold_version_id is not None:
        campaign.active_threshold_version_id = active_threshold_version_id
    if approved_rule_set_version_id is not None:
        campaign.approved_rule_set_version_id = approved_rule_set_version_id
    campaign.updated_by = actor_id
    db.flush()


# --- Closure readiness ----------------------------------------------------------------
#
# Before an authoriser marks a campaign COMPLETED (hiring finished) or CANCELLED (hiring
# abandoned), HR should be warned if work is still in flight: candidates mid-pipeline or
# interviews not yet concluded (Req 3: "warn HR if candidates or interviews are still
# pending"). This is ADVISORY ONLY — it never blocks the transition; the TransitionService
# remains the single authority on what moves are permitted. It is a pure read: no state is
# mutated and no records are touched.

# Application disposition states that are terminal for a campaign's purposes: the candidate
# has a final outcome (or withdrew), so they are NOT "pending". Everything else is pending
# work a closer should know about. Values mirror ApplicationState; kept as a literal set so
# this read does not depend on the applications module's internals.
_FINAL_APPLICATION_STATES: frozenset[str] = frozenset(
    {"selected", "rejected", "withdrawn"}
)

# Interview attendance values that mean the interview is concluded. Anything else
# (pending / checked_in) is an interview still in progress. Mirrors AttendanceStatus.
_CONCLUDED_ATTENDANCE: frozenset[str] = frozenset(
    {"checked_out", "attended", "no_show"}
)


class ClosureReadiness:
    """Advisory counts of in-flight work for a campaign about to be closed/cancelled."""

    __slots__ = ("pending_applications", "pending_interviews")

    def __init__(self, pending_applications: int, pending_interviews: int) -> None:
        self.pending_applications = pending_applications
        self.pending_interviews = pending_interviews

    @property
    def has_pending(self) -> bool:
        return self.pending_applications > 0 or self.pending_interviews > 0


def closure_readiness(
    db: Session, *, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> ClosureReadiness:
    """Count candidates and interviews still in progress for a campaign (advisory).

    Read-only. Used by the UI to warn before final closure; it does not gate the transition.
    Scoped by organisation and campaign (object-level authorisation is enforced on the route
    before this is called).
    """
    from sqlalchemy import func

    from app.modules.applications.models import Application
    from app.modules.interviews.models import InterviewInvitation

    pending_apps = db.execute(
        select(func.count())
        .select_from(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.campaign_id == campaign_id,
            Application.state.notin_(_FINAL_APPLICATION_STATES),
        )
    ).scalar_one()

    pending_interviews = db.execute(
        select(func.count())
        .select_from(InterviewInvitation)
        .where(
            InterviewInvitation.organisation_id == organisation_id,
            InterviewInvitation.campaign_id == campaign_id,
            InterviewInvitation.attendance.notin_(_CONCLUDED_ATTENDANCE),
        )
    ).scalar_one()

    return ClosureReadiness(
        pending_applications=int(pending_apps),
        pending_interviews=int(pending_interviews),
    )
