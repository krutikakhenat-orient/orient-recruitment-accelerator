"""Tests for JD upload, extraction, versioning and immutability (Req 3.1-3.3, AC-02)."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ConflictError
from app.modules.extraction.jd_extractor import extract_jd_draft
from app.modules.job_descriptions import service
from app.modules.job_descriptions.schemas import JDVersionUpdate
from tests.factories import make_org

JD_TEXT = b"""Position Title: Synthetic Platform Engineer
Department: Infrastructure
Location: Remote
Employment Type: Full-time
Number of openings: 2
Minimum 3 years experience with virtualization

Responsibilities:
- Operate synthetic clusters
- Automate deployments

Mandatory skills:
- Linux
- Networking
"""


def _upload(db_session, org):  # type: ignore[no-untyped-def]
    return service.upload_jd(
        db_session,
        organisation_id=org.id,
        campaign_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        filename="jd.txt",
        declared_content_type="text/plain",
        data=JD_TEXT,
    )


def test_extraction_proposes_labelled_fields_only() -> None:
    draft = extract_jd_draft(JD_TEXT.decode())
    names = {f.name for f in draft.fields}
    assert "position_title" in names
    assert "department" in names
    assert "minimum_total_experience_years" in names
    # Responsibilities and skills collected from their sections.
    assert any("synthetic clusters" in r.lower() for r in draft.responsibilities)
    assert "Linux" in draft.mandatory_skills
    # No field is invented when there is no labelled signal.
    assert "salary" not in names


def test_upload_creates_draft_with_extraction(db_session) -> None:
    org = make_org(db_session)
    version = _upload(db_session, org)
    assert version.status == "draft"
    assert version.version_number == 1
    assert version.position_title == "Synthetic Platform Engineer"
    assert version.extraction_draft is not None
    assert version.extraction_draft["ok"] is True


def test_approved_version_is_immutable(db_session) -> None:
    org = make_org(db_session)
    version = _upload(db_session, org)
    approved = service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed and approved",
    )
    assert approved.is_approved
    # Editing an approved version is refused.
    with pytest.raises(ConflictError, match="immutable"):
        service.update_jd_version(
            db_session, organisation_id=org.id, jd_version_id=version.id,
            actor_id=uuid.uuid4(), data=JDVersionUpdate(position_title="Changed"),
        )


def test_revision_preserves_original_and_increments_version(db_session) -> None:
    org = make_org(db_session)
    v1 = _upload(db_session, org)
    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=v1.id,
        actor_id=uuid.uuid4(), change_reason="approve v1",
    )
    v2 = service.revise_jd_version(
        db_session, organisation_id=org.id, approved_version_id=v1.id, actor_id=uuid.uuid4()
    )
    assert v2.version_number == 2
    assert v2.status == "draft"
    # Original remains approved and unchanged.
    assert v1.is_approved
    assert v1.position_title == v2.position_title


def test_cannot_approve_without_position_title(db_session) -> None:
    org = make_org(db_session)
    version = service.upload_jd(
        db_session, organisation_id=org.id, campaign_id=uuid.uuid4(), actor_id=uuid.uuid4(),
        filename="empty.txt", declared_content_type="text/plain",
        data=b"no labelled fields here at all",
    )
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError, match="position title"):
        service.approve_jd_version(
            db_session, organisation_id=org.id, jd_version_id=version.id,
            actor_id=uuid.uuid4(), change_reason="try approve",
        )


def test_approving_jd_wires_the_campaign_pointer(db_session) -> None:
    # Regression: approving a JD must set the owning campaign's approved_jd_version_id, so
    # downstream steps ("Generate scoring rules from JD") don't keep reporting
    # "Approve a Job Description first".
    from app.modules.campaigns.models import Campaign
    from app.modules.campaigns.states import CampaignState

    org = make_org(db_session)
    campaign = Campaign(
        organisation_id=org.id, project_id=uuid.uuid4(),
        name="SYNTHETIC Campaign", position_title="Synthetic Platform Engineer",
        number_of_openings=1, state=CampaignState.DRAFT.value,
    )
    db_session.add(campaign)
    db_session.flush()
    assert campaign.approved_jd_version_id is None

    version = service.upload_jd(
        db_session, organisation_id=org.id, campaign_id=campaign.id, actor_id=uuid.uuid4(),
        filename="jd.txt", declared_content_type="text/plain", data=JD_TEXT,
    )
    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed",
    )
    db_session.refresh(campaign)
    assert campaign.approved_jd_version_id == version.id


# --- Automatic JD-derived criteria + default 50% threshold on approval --------------------


def _campaign_with_jd(db_session, org, jd_text):  # type: ignore[no-untyped-def]
    """A real campaign with an uploaded JD (draft), ready to approve."""
    from app.modules.campaigns.models import Campaign
    from app.modules.campaigns.states import CampaignState

    campaign = Campaign(
        organisation_id=org.id, project_id=uuid.uuid4(),
        name="SYNTHETIC Auto Criteria", position_title="Synthetic Platform Engineer",
        number_of_openings=1, state=CampaignState.DRAFT.value,
    )
    db_session.add(campaign)
    db_session.flush()
    version = service.upload_jd(
        db_session, organisation_id=org.id, campaign_id=campaign.id, actor_id=uuid.uuid4(),
        filename="jd.txt", declared_content_type="text/plain", data=jd_text,
    )
    return campaign, version


def test_jd_approval_auto_generates_and_approves_criteria(db_session) -> None:
    """Approving a JD must auto-create + APPROVE scoring criteria and set a default 50%
    threshold — no manual Rule Set step needed. Four-eyes is preserved: the criteria are
    authored by the system identity and approved by the (different) human JD-approver."""
    from app.modules.rules.models import ApprovalStatus, RuleSetVersion, ThresholdVersion

    org = make_org(db_session)
    campaign, version = _campaign_with_jd(db_session, org, JD_TEXT)
    human_approver = uuid.uuid4()

    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=human_approver, change_reason="reviewed",
    )
    db_session.refresh(campaign)

    # An APPROVED rule-set is now wired to the campaign (screening can use it).
    assert campaign.approved_rule_set_version_id is not None
    rsv = db_session.get(RuleSetVersion, campaign.approved_rule_set_version_id)
    assert rsv is not None
    assert rsv.status == ApprovalStatus.APPROVED.value
    assert len(rsv.rules) >= 1  # JD had skills + experience -> non-empty criteria
    # Four-eyes held: system authored, human approved (distinct ids).
    assert rsv.created_by != rsv.approved_by
    assert rsv.approved_by == human_approver

    # A default 50% threshold is active (review_below == recommend_at_or_above == 50).
    assert campaign.active_threshold_version_id is not None
    tv = db_session.get(ThresholdVersion, campaign.active_threshold_version_id)
    assert tv is not None
    assert tv.review_below == 50.0
    assert tv.recommend_at_or_above == 50.0


def test_jd_reapproval_is_idempotent_no_duplicate_criteria(db_session) -> None:
    """Re-running auto-generation (e.g. a revised JD re-approved) must not create a second
    approved rule-set or a duplicate threshold for the campaign."""
    from sqlalchemy import func, select

    from app.modules.rules.models import RuleSet, RuleSetVersion, ThresholdSet, ThresholdVersion
    from app.modules.rules.service import auto_generate_criteria_on_jd_approval

    org = make_org(db_session)
    campaign, version = _campaign_with_jd(db_session, org, JD_TEXT)
    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed",
    )
    db_session.refresh(campaign)
    first_rsv = campaign.approved_rule_set_version_id
    first_tv = campaign.active_threshold_version_id

    # Call auto-generation again directly (simulates a retry / re-approval).
    result = auto_generate_criteria_on_jd_approval(
        db_session, organisation_id=org.id, campaign_id=campaign.id,
        approver_id=uuid.uuid4(),
    )
    assert result is None  # already had approved criteria -> no new version
    db_session.refresh(campaign)
    assert campaign.approved_rule_set_version_id == first_rsv
    assert campaign.active_threshold_version_id == first_tv

    # Exactly one approved rule-set version and one threshold version for this campaign.
    rs_ids = [r.id for r in db_session.execute(
        select(RuleSet).where(RuleSet.campaign_id == campaign.id)).scalars()]
    approved_count = db_session.execute(
        select(func.count()).select_from(RuleSetVersion)
        .where(RuleSetVersion.rule_set_id.in_(rs_ids),
               RuleSetVersion.status == "approved")
    ).scalar_one()
    assert approved_count == 1
    ts_ids = [t.id for t in db_session.execute(
        select(ThresholdSet).where(ThresholdSet.campaign_id == campaign.id)).scalars()]
    tv_count = db_session.execute(
        select(func.count()).select_from(ThresholdVersion)
        .where(ThresholdVersion.threshold_set_id.in_(ts_ids))
    ).scalar_one()
    assert tv_count == 1


def test_jd_with_no_criteria_warns_and_leaves_no_rule_set(db_session) -> None:
    """A JD that yields no usable skills/experience must NOT produce empty criteria. The JD
    still approves, but the campaign is left without approved criteria (manual review)."""
    # A JD with a position title (so approval is allowed) but no skills/experience section.
    jd_text = b"Position Title: Synthetic Role\nDepartment: Ops\nLocation: Remote\n"
    org = make_org(db_session)
    campaign, version = _campaign_with_jd(db_session, org, jd_text)

    approved = service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed",
    )
    assert approved.is_approved  # JD approval itself succeeds
    db_session.refresh(campaign)
    # No approved rule-set (we never invent empty criteria); a threshold default may still be
    # set, but the campaign cannot screen/publish until real criteria exist.
    assert campaign.approved_rule_set_version_id is None


def test_regenerate_criteria_refreshes_stale_rule_set(db_session) -> None:
    """regenerate_criteria_from_jd repairs a campaign whose approved rule-set has no skill
    criteria (the 0/100 cause): it builds fresh JD-derived criteria INCLUDING skills and
    repoints the campaign, even though an approved rule-set already exists."""
    from app.modules.rules import service as rules_service
    from app.modules.rules.models import RuleSetVersion

    org = make_org(db_session)
    campaign, version = _campaign_with_jd(db_session, org, JD_TEXT)  # JD has Linux/Networking
    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed",
    )
    db_session.refresh(campaign)
    first_rsv_id = campaign.approved_rule_set_version_id
    assert first_rsv_id is not None

    # Simulate a STALE approved rule-set with only experience/notice (no skills) by pointing
    # the campaign at a hand-authored version like the old "starter set".
    stale = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=campaign.id, name="stale starter",
        rules=[{
            "rule_id": "R-TOTAL-EXP", "name": "Minimum total experience",
            "criterion_type": "numeric_comparison", "field": "total_experience_years",
            "operator": "gte", "expected_value": 3, "weight": 40, "mandatory": True,
            "missing_evidence": "manual_review",
        }],
        actor_id=uuid.uuid4(),
    )
    rules_service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=stale.id, approver_id=uuid.uuid4(),
    )
    db_session.refresh(campaign)
    assert campaign.approved_rule_set_version_id == stale.id
    stale_names = {r["name"] for r in stale.rules}
    assert not any("skill" in n.lower() or n in ("Linux", "Networking") for n in stale_names)

    # Regenerate: must create a NEW approved rule-set WITH skill criteria and repoint.
    new_version = rules_service.regenerate_criteria_from_jd(
        db_session, organisation_id=org.id, campaign_id=campaign.id, approver_id=uuid.uuid4(),
    )
    db_session.refresh(campaign)
    assert campaign.approved_rule_set_version_id == new_version.id
    assert new_version.id not in (first_rsv_id, stale.id)
    names = {r["name"] for r in new_version.rules}
    # Skill criteria from the JD are now present (Linux / Networking).
    assert any(n in ("Linux", "Networking") for n in names)
    # Four-eyes preserved (system author != human approver).
    rsv = db_session.get(RuleSetVersion, new_version.id)
    assert rsv is not None and rsv.created_by != rsv.approved_by
    # The stale version remains immutable in history.
    assert db_session.get(RuleSetVersion, stale.id).rules == stale.rules


def test_auto_generate_regenerates_when_existing_rule_set_has_no_skill_criteria(
    db_session,
) -> None:
    """THE 'new JD still gives 0' fix. If a campaign already has an approved rule-set that
    contains NO skill criteria (a stale experience/notice starter set), re-running the JD
    auto-configuration must REGENERATE JD-derived criteria (with skills) instead of no-oping.
    Previously the idempotency guard short-circuited on ANY existing rule-set, leaving the
    campaign permanently skill-less so every candidate scored 0."""
    from app.modules.rules import service as rules_service
    from app.modules.rules.models import RuleSetVersion
    from app.modules.rules.service import auto_generate_criteria_on_jd_approval

    org = make_org(db_session)
    campaign, version = _campaign_with_jd(db_session, org, JD_TEXT)  # JD has Linux/Networking
    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed",
    )
    db_session.refresh(campaign)

    # Force the campaign onto a stale approved rule-set with NO skill criteria.
    stale = rules_service.create_rule_set_version(
        db_session, organisation_id=org.id, campaign_id=campaign.id, name="stale starter",
        rules=[{
            "rule_id": "R-TOTAL-EXP", "name": "Minimum total experience",
            "criterion_type": "numeric_comparison", "field": "total_experience_years",
            "operator": "gte", "expected_value": 3, "weight": 40, "mandatory": True,
            "missing_evidence": "manual_review",
        }],
        actor_id=uuid.uuid4(),
    )
    rules_service.approve_rule_set_version(
        db_session, organisation_id=org.id, version_id=stale.id, approver_id=uuid.uuid4(),
    )
    db_session.refresh(campaign)
    assert campaign.approved_rule_set_version_id == stale.id

    # Re-run auto-configuration (what happens when the JD is re-approved). It must NOT no-op:
    # it must build a fresh JD-derived set that includes skill criteria.
    result = auto_generate_criteria_on_jd_approval(
        db_session, organisation_id=org.id, campaign_id=campaign.id, approver_id=uuid.uuid4(),
    )
    assert result is not None, "must regenerate, not no-op, when no skill criteria exist"
    db_session.refresh(campaign)
    assert campaign.approved_rule_set_version_id == result.id
    names = {r["name"] for r in result.rules}
    assert any(n in ("Linux", "Networking") for n in names), "regenerated set must have skills"

    # And when the approved set ALREADY has skill criteria, a re-run is a genuine no-op.
    again = auto_generate_criteria_on_jd_approval(
        db_session, organisation_id=org.id, campaign_id=campaign.id, approver_id=uuid.uuid4(),
    )
    assert again is None
    rsv = db_session.get(RuleSetVersion, result.id)
    assert rsv is not None and rsv.created_by != rsv.approved_by  # four-eyes preserved


def test_rescore_progresses_high_scorers_to_panel_and_leaves_low_in_queue(db_session) -> None:
    """rescore_campaign must place clean >=50 candidates on the Interview Panel worklist
    (state interview_scheduled) and leave <50 / review candidates off it."""
    from app.modules.applications.models import Application
    from app.modules.applications.states import ApplicationState
    from app.modules.assessments.service import panel_worklist
    from app.modules.extraction.models import ExtractedField, VerificationStatus
    from app.modules.identity.permissions import Permission
    from app.modules.identity.schemas import AuthenticatedActor
    from app.modules.screening import service as screening_service

    org = make_org(db_session)
    campaign, version = _campaign_with_jd(db_session, org, JD_TEXT)  # Linux+Networking, 3y
    service.approve_jd_version(
        db_session, organisation_id=org.id, jd_version_id=version.id,
        actor_id=uuid.uuid4(), change_reason="reviewed",
    )

    def _app(resume_text: str, answers: dict) -> Application:  # type: ignore[type-arg]
        app = Application(
            organisation_id=org.id, campaign_id=campaign.id, candidate_id=uuid.uuid4(),
            form_version_id=uuid.uuid4(), answers=answers,
            state=ApplicationState.EXTRACTION_REVIEW.value,
        )
        db_session.add(app)
        db_session.flush()
        db_session.add(ExtractedField(
            organisation_id=org.id, application_id=app.id, field_name="resume_text",
            extracted_value=resume_text, status=VerificationStatus.VERIFIED.value,
            extraction_method="manual", confidence=1.0,
        ))
        db_session.flush()
        return app

    # High scorer: both mandatory skills present in the resume + enough experience.
    high = _app(
        "Senior engineer. Skilled in Linux and Networking. 6 years experience.",
        {"total_experience_years": "6", "current_location": "Remote"},
    )
    # Low scorer: neither skill, no experience -> mandatory skills route to review, < 50.
    low = _app("Junior candidate with graphic design background.", {})

    actor = AuthenticatedActor(
        user_id=uuid.uuid4(), organisation_id=org.id, email="rescore@example.com",
        role_names=["recruiter_admin"],
        permissions={
            Permission.CAMPAIGN_EDIT.value, Permission.SCREENING_EXECUTE.value,
            Permission.APPLICATION_REVIEW.value, Permission.RULE_CREATE.value,
            Permission.RULE_APPROVE.value, Permission.THRESHOLD_CHANGE.value,
            Permission.INTERVIEW_APPROVE.value, Permission.INTERVIEW_SCHEDULE.value,
        },
        assigned_campaign_ids={campaign.id},
    )
    summary = screening_service.rescore_campaign(
        db_session, organisation_id=org.id, campaign_id=campaign.id, actor=actor,
    )
    assert summary.rescored == 2
    assert summary.progressed == 1  # only the high scorer

    db_session.refresh(high)
    db_session.refresh(low)
    # High scorer is on the panel (scheduled); low scorer is NOT.
    assert high.state == ApplicationState.INTERVIEW_SCHEDULED.value
    assert low.state != ApplicationState.INTERVIEW_SCHEDULED.value

    worklist_ids = {w["application_id"] for w in panel_worklist(db_session, org.id)}
    assert high.id in worklist_ids
    assert low.id not in worklist_ids
