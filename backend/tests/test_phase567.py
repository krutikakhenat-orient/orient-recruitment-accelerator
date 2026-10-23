"""Tests for Phase 5-7: interviews, assessments, decisions, waitlist/re-eval,
talent pool, privacy/retention, reporting (Req 10.*, 11.*, 14.*, 15.*; AC-13, AC-14, AC-17)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.errors import ConflictError, SeparationOfDutiesError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.assessments import service as assessment_service
from app.modules.assessments.models import AssessmentRecommendation
from app.modules.candidates import service as candidate_service
from app.modules.candidates.models import ConsentPurpose
from app.modules.decisions import service as decision_service
from app.modules.decisions.models import DecisionType
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import DEFAULT_ROLE_PERMISSIONS, RoleName
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews import service as interview_service
from app.modules.privacy import service as privacy_service
from app.modules.privacy.models import (
    PrivacyRequestType,
    RecordCategory,
    RetentionActionType,
)
from app.modules.reporting import service as reporting_service
from app.modules.talent_pool import service as talent_service
from tests.factories import make_org

CAMPAIGN = uuid.uuid4()


def _actor(org, user_id, role: RoleName) -> AuthenticatedActor:  # type: ignore[no-untyped-def]
    perms = {p.value for p in DEFAULT_ROLE_PERMISSIONS[role]}
    # Grant the broad set needed to drive the whole flow in one actor for the test.
    perms |= {
        "interview.approve", "interview.schedule", "assessment.submit",
        "hiring_decision.approve", "hiring_decision.recommend", "waitlist.manage",
    }
    return AuthenticatedActor(
        user_id=user_id, organisation_id=org.id, email="synthetic@example.com",
        role_names=[role.value], permissions=perms, assigned_campaign_ids={CAMPAIGN},
    )


def _application(db_session, org, state: ApplicationState) -> Application:  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id, campaign_id=CAMPAIGN, candidate_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(), answers={}, state=state.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def test_interview_flow_through_to_decision(db_session) -> None:
    org = make_org(db_session)
    actor = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app = _application(db_session, org, ApplicationState.SCREENED)

    # Approve interview (AC-14): application -> interview_recommended.
    invitation = interview_service.approve_invitation(db_session, actor=actor, application=app)
    assert app.state == ApplicationState.INTERVIEW_RECOMMENDED.value

    # Create a stage + slot, assign & confirm -> interview_scheduled.
    stage = interview_service.create_stage(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="Technical",
        sequence=1, actor_id=actor.user_id,
    )
    slot = interview_service.create_slot(
        db_session, organisation_id=org.id, stage_id=stage.id, slot_date=dt.date.today(),
        start_time="10:00", location="HQ", mode="in_person", capacity=1,
        actor_id=actor.user_id,
    )
    interview_service.assign_slot_and_confirm(
        db_session, actor=actor, invitation_id=invitation.id, slot_id=slot.id
    )
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value

    # Attendance -> attended.
    interview_service.record_attendance(
        db_session, actor=actor, invitation_id=invitation.id, attended=True
    )
    assert app.state == ApplicationState.ATTENDED.value

    # Assessment -> assessed.
    assessment_service.submit_assessment(
        db_session, actor=actor, application=app, criteria_scores={"technical": 4},
        recommendation=AssessmentRecommendation.PROCEED,
    )
    assert app.state == ApplicationState.ASSESSED.value

    # Decision (select) -> selected.
    decision_service.record_decision(
        db_session, actor=actor, application=app, decision_type=DecisionType.SELECT,
        reason="strong performance",
    )
    assert app.state == ApplicationState.SELECTED.value


def _panel_actor(org) -> AuthenticatedActor:  # type: ignore[no-untyped-def]
    """A real Interview Panel member: ONLY assessment.submit, NOT assigned to the campaign."""
    return AuthenticatedActor(
        user_id=uuid.uuid4(), organisation_id=org.id, email="panel@example.com",
        role_names=[RoleName.INTERVIEW_PANEL.value],
        permissions={"assessment.submit"}, assigned_campaign_ids=set(),
    )


def _scheduled_invitation(db_session, org, admin):  # type: ignore[no-untyped-def]
    app = _application(db_session, org, ApplicationState.SCREENED)
    inv = interview_service.approve_invitation(db_session, actor=admin, application=app)
    stage = interview_service.create_stage(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="Tech", sequence=1,
        actor_id=admin.user_id,
    )
    slot = interview_service.create_slot(
        db_session, organisation_id=org.id, stage_id=stage.id, slot_date=dt.date.today(),
        start_time="10:00", location="HQ", mode="in_person", capacity=1,
        actor_id=admin.user_id,
    )
    interview_service.assign_slot_and_confirm(
        db_session, actor=admin, invitation_id=inv.id, slot_id=slot.id
    )
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value
    return app, inv


def test_panel_member_can_record_attendance(db_session) -> None:
    # The Interview Panel (assessment.submit only, not campaign-assigned) marks attendance.
    org = make_org(db_session)
    admin = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app, inv = _scheduled_invitation(db_session, org, admin)

    interview_service.record_attendance(
        db_session, actor=_panel_actor(org), invitation_id=inv.id, attended=True
    )
    assert app.state == ApplicationState.ATTENDED.value


def test_recruiter_admin_without_assessment_submit_cannot_record_attendance(db_session) -> None:
    # Attendance is now the panel's job: a Recruiter Admin lacking assessment.submit cannot
    # mark attendance (the transition requires assessment.submit).
    from app.core.errors import PermissionDeniedError

    org = make_org(db_session)
    admin = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app, inv = _scheduled_invitation(db_session, org, admin)

    # A strict admin actor WITHOUT the broad grant (no assessment.submit).
    strict_admin = AuthenticatedActor(
        user_id=uuid.uuid4(), organisation_id=org.id, email="admin@example.com",
        role_names=[RoleName.RECRUITER_ADMIN.value],
        permissions={"interview.approve", "interview.schedule"},
        assigned_campaign_ids={CAMPAIGN},
    )
    with pytest.raises(PermissionDeniedError):
        interview_service.record_attendance(
            db_session, actor=strict_admin, invitation_id=inv.id, attended=True
        )
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value


def test_panel_worklist_groups_by_stage(db_session) -> None:
    org = make_org(db_session)
    admin = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app, inv = _scheduled_invitation(db_session, org, admin)

    work = assessment_service.panel_worklist(db_session, org.id)
    mine = next(w for w in work if w["application_id"] == app.id)
    # A scheduled candidate is awaiting check-in in the new flow.
    assert mine["stage"] == "to_check_in"
    assert mine["invitation_id"] == inv.id

    # After the legacy attendance path it becomes "to_assess" (legacy ATTENDED rows are
    # still mapped to the assess stage so historical records remain workable).
    interview_service.record_attendance(
        db_session, actor=_panel_actor(org), invitation_id=inv.id, attended=True
    )
    work = assessment_service.panel_worklist(db_session, org.id)
    mine = next(w for w in work if w["application_id"] == app.id)
    assert mine["stage"] == "to_assess"


def test_slot_capacity_enforced(db_session) -> None:
    org = make_org(db_session)
    actor = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    stage = interview_service.create_stage(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="S", sequence=1,
        actor_id=actor.user_id,
    )
    slot = interview_service.create_slot(
        db_session, organisation_id=org.id, stage_id=stage.id, slot_date=dt.date.today(),
        start_time="10:00", location=None, mode="in_person", capacity=1,
        actor_id=actor.user_id,
    )
    app1 = _application(db_session, org, ApplicationState.SCREENED)
    inv1 = interview_service.approve_invitation(db_session, actor=actor, application=app1)
    interview_service.assign_slot_and_confirm(
        db_session, actor=actor, invitation_id=inv1.id, slot_id=slot.id
    )
    app2 = _application(db_session, org, ApplicationState.SCREENED)
    inv2 = interview_service.approve_invitation(db_session, actor=actor, application=app2)
    with pytest.raises(ConflictError, match="full"):
        interview_service.assign_slot_and_confirm(
            db_session, actor=actor, invitation_id=inv2.id, slot_id=slot.id
        )


def test_assessment_requires_checked_in(db_session) -> None:
    org = make_org(db_session)
    actor = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app = _application(db_session, org, ApplicationState.SCREENED)
    with pytest.raises(ConflictError, match="checked in"):
        assessment_service.submit_assessment(
            db_session, actor=actor, application=app, criteria_scores={},
            recommendation=AssessmentRecommendation.PROCEED,
        )


def test_assessment_conflict_requires_detail(db_session) -> None:
    org = make_org(db_session)
    actor = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app = _application(db_session, org, ApplicationState.ATTENDED)
    with pytest.raises(ValidationError, match="conflict detail"):
        assessment_service.submit_assessment(
            db_session, actor=actor, application=app, criteria_scores={},
            recommendation=AssessmentRecommendation.PROCEED, conflict_declared=True,
        )


def test_talent_pool_search_only_returns_consented(db_session) -> None:
    org = make_org(db_session)
    actor_id = uuid.uuid4()
    # Candidate A opted into talent pool; candidate B did not.
    a = candidate_service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="A", email="a@example.com", mobile=None,
    ).candidate
    candidate_service.record_consent(
        db_session, organisation_id=org.id, candidate_id=a.id,
        purpose=ConsentPurpose.TALENT_POOL, notice_version="v1",
    )
    candidate_service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="B", email="b@example.com", mobile=None,
    )
    matches = talent_service.search(
        db_session, organisation_id=org.id, actor_id=actor_id, skill_token="python"
    )
    emails = {m.email for m in matches}
    assert "a@example.com" in emails
    assert "b@example.com" not in emails
    # Match is advisory: must verify before contacting.
    assert all("Verify evidence" in m.note for m in matches)


def test_privacy_request_lifecycle_and_retention_logged(db_session) -> None:
    org = make_org(db_session)
    actor_id = uuid.uuid4()
    cand = candidate_service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="C", email="c@example.com", mobile=None,
    ).candidate

    req = privacy_service.create_privacy_request(
        db_session, organisation_id=org.id, candidate_id=cand.id,
        request_type=PrivacyRequestType.DELETION, detail="please erase", actor_id=actor_id,
    )
    assert req.status == "received"
    completed = privacy_service.complete_privacy_request(
        db_session, organisation_id=org.id, request_id=req.id, actor_id=actor_id,
    )
    assert completed.status == "completed"

    # Retention policy + a logged retention action (AC-17).
    privacy_service.set_retention_policy(
        db_session, organisation_id=org.id, category=RecordCategory.RESUME,
        retain_days=180, action_on_expiry=RetentionActionType.DELETE, actor_id=actor_id,
    )
    action = privacy_service.record_retention_action(
        db_session, organisation_id=org.id, category=RecordCategory.RESUME,
        action_type=RetentionActionType.ANONYMISE, target_entity_type="document",
        target_entity_id=str(uuid.uuid4()), reason="retention window elapsed",
        actor_id=actor_id,
    )
    assert action.action_type == "anonymise"


def test_retention_action_requires_reason(db_session) -> None:
    org = make_org(db_session)
    with pytest.raises(ValidationError, match="reason is required"):
        privacy_service.record_retention_action(
            db_session, organisation_id=org.id, category=RecordCategory.RESUME,
            action_type=RetentionActionType.DELETE, target_entity_type="document",
            target_entity_id="x", reason="  ", actor_id=uuid.uuid4(),
        )


def test_dashboards_aggregate_and_suppress(db_session) -> None:
    org = make_org(db_session)
    # A couple of applications in various states.
    _application(db_session, org, ApplicationState.SCREENED)
    _application(db_session, org, ApplicationState.SELECTED)

    hr = reporting_service.hr_dashboard(db_session, org.id)
    assert hr.applications_by_state.get("screened", 0) >= 1

    mgmt = reporting_service.management_dashboard(db_session, org.id)
    assert mgmt.total_applications >= 2
    # 1 selected candidate is a small group -> suppressed.
    assert mgmt.selected_candidates == "<5"


def test_rule_creator_cannot_approve_is_still_enforced(db_session) -> None:
    # Sanity re-check that SoD import path works alongside the new modules.
    from app.modules.rules import service as rules_service

    org = make_org(db_session)
    creator = uuid.uuid4()
    rules = [{"rule_id": "R", "name": "x", "criterion_type": "numeric_comparison",
              "field": "exp", "operator": "gte", "expected_value": 1, "weight": 5}]
    version = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=CAMPAIGN, name="rs", rules=rules,
        actor_id=creator,
    )
    with pytest.raises(SeparationOfDutiesError):
        rules_service.approve_rule_set_version(
            db_session, organisation_id=org.id, version_id=version.id, approver_id=creator,
        )


def test_campaign_assignment_model_present() -> None:
    # Ensures the identity assignment used for object-level authz is importable here.
    assert CampaignAssignment.__tablename__ == "campaign_assignment"


def test_approve_invitation_prevents_duplicates(db_session) -> None:
    """Selecting a candidate for interview twice must not create two live invitations."""
    import pytest

    from app.core.errors import ConflictError

    org = make_org(db_session)
    actor = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app = _application(db_session, org, ApplicationState.SCREENED)

    first = interview_service.approve_invitation(db_session, actor=actor, application=app)
    assert first is not None

    # The state has moved to INTERVIEW_RECOMMENDED; a second attempt is rejected both by the
    # state guard and the explicit active-invitation guard. Force the state back to SCREENED
    # to prove the active-invitation guard itself blocks the duplicate.
    app.state = ApplicationState.SCREENED.value
    db_session.flush()
    with pytest.raises(ConflictError, match="already has an active interview invitation"):
        interview_service.approve_invitation(db_session, actor=actor, application=app)

    # Exactly one invitation exists for this application.
    from sqlalchemy import func, select

    from app.modules.interviews.models import InterviewInvitation

    count = db_session.execute(
        select(func.count())
        .select_from(InterviewInvitation)
        .where(InterviewInvitation.application_id == app.id)
    ).scalar_one()
    assert count == 1


def test_select_under_review_candidate_requires_reason(db_session) -> None:
    """Selecting a BELOW-threshold (under-review) candidate for interview is a screening
    override and must carry a reason (security.md). A clean SCREENED candidate does not."""
    from app.modules.interviews.router import _require_override_reason_if_under_review

    org = make_org(db_session)

    under_review = _application(db_session, org, ApplicationState.MANUAL_REVIEW)
    # No reason -> rejected.
    with pytest.raises(ValidationError, match="reason is required"):
        _require_override_reason_if_under_review(under_review, None)
    with pytest.raises(ValidationError, match="reason is required"):
        _require_override_reason_if_under_review(under_review, "   ")
    # With a reason -> allowed (no exception).
    _require_override_reason_if_under_review(under_review, "Strong relevant project work")

    # A clean screened candidate needs no reason.
    screened = _application(db_session, org, ApplicationState.SCREENED)
    _require_override_reason_if_under_review(screened, None)


def test_walk_in_override_reason_is_recorded_in_audit(db_session) -> None:
    """When a sub-50 candidate is selected via the walk-in path with a reason, the reason is
    written to the invitation-approval audit event so the override is explainable."""
    from sqlalchemy import select

    from app.modules.audit.models import AuditEvent

    org = make_org(db_session)
    actor = _actor(org, uuid.uuid4(), RoleName.RECRUITER_ADMIN)
    app = _application(db_session, org, ApplicationState.MANUAL_REVIEW)

    interview_service.record_walk_in_interview(
        db_session, actor=actor, application=app, reason="Exceptional portfolio",
    )
    assert app.state == ApplicationState.INTERVIEW_SCHEDULED.value

    events = list(db_session.execute(
        select(AuditEvent).where(
            AuditEvent.organisation_id == org.id,
            AuditEvent.action == "interview.invitation_approved",
        )
    ).scalars())
    assert any(e.reason == "Exceptional portfolio" for e in events)
