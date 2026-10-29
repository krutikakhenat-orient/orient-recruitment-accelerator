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
