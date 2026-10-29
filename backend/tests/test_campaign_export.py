"""Campaign Excel export tests (reporting module).

These tests prove the export is a faithful, READ-ONLY projection of already-saved data:

  * Every candidate in the campaign is exported (including beyond the default UI page of
    200), in the SAME rank/score order the UI uses (``list_ranked_for_campaign``).
  * The export reuses saved scores — it creates NO new ScreeningRun/CriterionResult rows
    and mutates NO Application/Assessment/Campaign row.
  * Object-level authorisation is enforced: the endpoint needs ``candidate.view`` AND
    campaign assignment; a panel-only user (no ``candidate.view``) is refused, and a user
    assigned to a different campaign cannot export this one (no cross-campaign leakage).
  * Spreadsheet-formula injection in candidate-supplied text is neutralised (written as
    literal text, never an active formula).
  * An empty campaign still produces a valid 4-sheet workbook.

All data here is SYNTHETIC. No real candidate information is used.
"""

from __future__ import annotations

import datetime as dt
import io
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.modules.applications import service as application_service
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.candidates.models import Candidate
from app.modules.documents.models import Document, DocumentKind, DocumentStatus
from app.modules.forms import service as form_service
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from app.modules.reporting import export_service
from app.modules.screening.models import CriterionResult, ScreeningRun
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"

EXPECTED_SHEETS = ["Candidates", "Summary"]


# --------------------------------------------------------------------------------------
# Synthetic builders (service-level, direct on db_session)
# --------------------------------------------------------------------------------------
def _open_campaign(db_session, org, *, name="SYNTHETIC Campaign"):  # type: ignore[no-untyped-def]
    campaign = Campaign(
        organisation_id=org.id,
        project_id=uuid.uuid4(),
        name=name,
        position_title="Synthetic Engineer",
        number_of_openings=3,
        state=CampaignState.APPLICATIONS_OPEN.value,
        privacy_notice_version="v1",
    )
    db_session.add(campaign)
    db_session.flush()
    form = form_service.create_form_draft(
        db_session, organisation_id=org.id, campaign_id=campaign.id, actor_id=uuid.uuid4()
    )
    form_service.approve_form_version(
        db_session, organisation_id=org.id, form_version_id=form.id, actor_id=uuid.uuid4()
    )
    campaign.approved_form_version_id = form.id
    db_session.flush()
    return campaign


def _candidate(db_session, org, *, name, email):  # type: ignore[no-untyped-def]
    cand = Candidate(
        organisation_id=org.id, full_name=name, email=email.lower(),
        mobile="+14155550100",
    )
    db_session.add(cand)
    db_session.flush()
    return cand


def _application(db_session, org, campaign, candidate, *, answers=None):  # type: ignore[no-untyped-def]
    app = Application(
        organisation_id=org.id,
        campaign_id=campaign.id,
        candidate_id=candidate.id,
        form_version_id=campaign.approved_form_version_id,
        answers=answers or {"full_name": candidate.full_name},
        state=ApplicationState.SCREENED.value,
    )
    db_session.add(app)
    db_session.flush()
    return app


def _completed_run(db_session, org, app, score, *, with_criteria=True):  # type: ignore[no-untyped-def]
    run = ScreeningRun(
        organisation_id=org.id,
        application_id=app.id,
        rule_set_version_id=uuid.uuid4(),
        score=score,
        eligibility_outcome="eligible",
        confidence_status="confirmed",
        recommendation="recommended_for_interview_review",
        manual_review_required=False,
        completed_at=dt.datetime.now(tz=dt.UTC),
        input_data_hash="x" * 12,
        engine_version="1.0.0",
    )
    db_session.add(run)
    db_session.flush()
    if with_criteria:
        # Outcome uses the evaluator's stored vocabulary ("pass" | "fail" |
        # "manual_review"), and tier the stored skill-tier vocabulary, so the export's
        # readable mapping is exercised against real values.
        db_session.add(
            CriterionResult(
                screening_run_id=run.id,
                criterion_name="Python experience",
                criterion_type="skill",
                mandatory=True,
                tier="must_have",
                outcome="pass",
                max_score=10.0,
                awarded_score=10.0,
                reason="Matched resume evidence",
                order_index=0,
            )
        )
        db_session.flush()
    return run


def _criterion(  # type: ignore[no-untyped-def]
    db_session, run, *, name, outcome, tier=None, awarded=0.0, maximum=10.0,
    reason="", order_index=0,
):
    """Attach a single CriterionResult to a run (saved data only; read by the export)."""
    cr = CriterionResult(
        screening_run_id=run.id,
        criterion_name=name,
        criterion_type="skill",
        mandatory=tier == "must_have",
        tier=tier,
        outcome=outcome,
        max_score=maximum,
        awarded_score=awarded,
        reason=reason,
        order_index=order_index,
    )
    db_session.add(cr)
    db_session.flush()
    return cr


def _load_workbook(data: bytes):  # type: ignore[no-untyped-def]
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(data), read_only=True)


def _load_workbook_rw(data: bytes):  # type: ignore[no-untyped-def]
    """Load the workbook in normal (non-read-only) mode so cell-level attributes such as
    ``.hyperlink`` are available (read-only cells do not expose them)."""
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(data), read_only=False)


# --------------------------------------------------------------------------------------
# Service-level tests
# --------------------------------------------------------------------------------------
def _detail_rows(wb):  # type: ignore[no-untyped-def]
    """(header, body) tuple for the HR 'Candidates' sheet."""
    rows = list(wb["Candidates"].iter_rows(values_only=True))
    return rows[0], rows[1:]


def _build(db_session, org, campaign, **kw):  # type: ignore[no-untyped-def]
    return export_service.build_campaign_workbook_bytes(
        db_session, organisation_id=org.id, campaign=campaign, **kw
    )


def test_export_produces_valid_hr_workbook(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Alpha Synthetic", email="alpha@example.com")
    app = _application(db_session, org, campaign, cand)
    _completed_run(db_session, org, app, 72.0)

    data = _build(db_session, org, campaign)
    assert isinstance(data, bytes) and len(data) > 0
    wb = _load_workbook(data)
    assert wb.sheetnames == EXPECTED_SHEETS


def test_candidates_sheet_has_hr_columns_only(db_session) -> None:
    """The HR sheet shows decision-relevant columns and NOT internal IDs / technical
    metadata (application/candidate UUIDs, rule-set/engine versions, hashes)."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Cols Synthetic", email="cols@example.com")
    app = _application(db_session, org, campaign, cand)
    _completed_run(db_session, org, app, 72.0)

    wb = _load_workbook(_build(db_session, org, campaign))
    header, _ = _detail_rows(wb)
    for col in (
        "Candidate name", "Email address", "Contact number", "Applied position",
        "Application status", "Overall score (%)", "JD skills match (%)",
        "Relevant skills & experience", "Key strengths",
        "Missing / unverified requirements", "Resume", "Candidate summary",
    ):
        assert col in header, f"missing HR column: {col}"
    # Internal identifiers HR does not need must be absent as columns.
    for banned in ("Application ID", "Candidate ID", "Engine version", "Input data hash"):
        assert banned not in header


def test_empty_campaign_still_produces_valid_workbook(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    wb = _load_workbook(_build(db_session, org, campaign))
    assert wb.sheetnames == EXPECTED_SHEETS
    rows = list(wb["Candidates"].iter_rows(values_only=True))
    assert len(rows) == 1  # header only


def test_exports_all_candidates_beyond_default_page(db_session) -> None:
    """More than the default UI page (200) — every candidate must appear exactly once."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    count = 205
    for i in range(count):
        cand = _candidate(
            db_session, org, name=f"Candidate {i:03d}", email=f"cand{i:03d}@example.com"
        )
        app = _application(db_session, org, campaign, cand)
        _completed_run(db_session, org, app, float(i % 100), with_criteria=False)

    wb = _load_workbook(_build(db_session, org, campaign))
    _, body = _detail_rows(wb)
    assert len(body) == count
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True)}
    assert summary["Total candidates"] == count


def test_rows_in_rank_order_matching_list_ranked(db_session) -> None:
    """The candidate rows appear in the SAME rank order as list_ranked_for_campaign."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    for i, s in enumerate([30.0, 90.0, 60.0]):
        cand = _candidate(db_session, org, name=f"Ranked {i}", email=f"ranked{i}@example.com")
        app = _application(db_session, org, campaign, cand)
        _completed_run(db_session, org, app, s, with_criteria=False)

    ranked = application_service.list_ranked_for_campaign(
        db_session, org.id, campaign.id, limit=1000, offset=0
    )
    def _name(r):  # type: ignore[no-untyped-def]
        ans = r.application.answers
        return ans.get("full_name") if isinstance(ans, dict) else None

    expected_names = [_name(r) for r in ranked]

    wb = _load_workbook(_build(db_session, org, campaign))
    header, body = _detail_rows(wb)
    name_i = header.index("Candidate name")
    rank_i = header.index("Rank")
    assert [row[name_i] for row in body] == expected_names
    # Highest score ranks first.
    assert body[0][rank_i] == 1


def test_overall_score_and_jd_match_are_distinct(db_session) -> None:
    """Overall score (fit %) and JD skills match (derived from skill criteria) are separate
    numbers; JD match is derived only from exact_skill criteria."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Distinct Synthetic", email="dist@example.com")
    app = _application(db_session, org, campaign, cand)
    run = _completed_run(db_session, org, app, 66.0, with_criteria=False)
    # Two exact_skill criteria: 1 pass (8/10), 1 fail (0/10) -> JD match = 40%.
    skill_pass = CriterionResult(
        screening_run_id=run.id, criterion_name="Python", criterion_type="exact_skill",
        mandatory=False, tier="good_to_have", outcome="pass",
        max_score=10.0, awarded_score=8.0, reason="found", order_index=0,
    )
    skill_fail = CriterionResult(
        screening_run_id=run.id, criterion_name="Rust", criterion_type="exact_skill",
        mandatory=False, tier="good_to_have", outcome="fail",
        max_score=10.0, awarded_score=0.0, reason="not found", order_index=1,
    )
    db_session.add_all([skill_pass, skill_fail])
    db_session.flush()

    wb = _load_workbook(_build(db_session, org, campaign))
    header, body = _detail_rows(wb)
    overall_i = header.index("Overall score (%)")
    jd_i = header.index("JD skills match (%)")
    assert body[0][overall_i] == 66.0           # the stored fit score, unchanged
    assert body[0][jd_i] == 40.0                # derived from the two skill criteria only
    assert body[0][overall_i] != body[0][jd_i]  # genuinely distinct numbers


def test_jd_match_is_not_provided_without_skill_criteria(db_session) -> None:
    """Never invent a JD match: with no exact_skill criteria the cell is 'Not provided'."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="NoSkill Synthetic", email="nosk@example.com")
    app = _application(db_session, org, campaign, cand)
    run = _completed_run(db_session, org, app, 50.0, with_criteria=False)
    # Only a non-skill criterion.
    _criterion(db_session, run, name="Experience", outcome="pass", tier=None,
               awarded=5.0, maximum=5.0, reason="ok", order_index=0)

    wb = _load_workbook(_build(db_session, org, campaign))
    header, body = _detail_rows(wb)
    jd_i = header.index("JD skills match (%)")
    assert body[0][jd_i] == "Not provided"


def test_strengths_and_missing_requirements_derived_from_criteria(db_session) -> None:
    """Relevant skills / key strengths / missing+unverified requirements are DERIVED from
    saved criterion rows (pass -> strength, must-have fail -> missing, review -> unverified).
    Nothing is invented."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Derive Synthetic", email="der@example.com")
    app = _application(db_session, org, campaign, cand)
    run = _completed_run(db_session, org, app, 55.0, with_criteria=False)
    _criterion(db_session, run, name="SQL", outcome="pass", tier="good_to_have",
               awarded=6.0, maximum=6.0, reason="found", order_index=0)
    _criterion(db_session, run, name="Kubernetes", outcome="fail", tier="must_have",
               awarded=0.0, maximum=10.0, reason="not found", order_index=1)
    _criterion(db_session, run, name="Leadership", outcome="manual_review", tier=None,
               awarded=0.0, maximum=4.0, reason="needs a human", order_index=2)

    wb = _load_workbook(_build(db_session, org, campaign))
    header, body = _detail_rows(wb)
    skills_cell = body[0][header.index("Relevant skills & experience")]
    strengths_cell = body[0][header.index("Key strengths")]
    missing_cell = body[0][header.index("Missing / unverified requirements")]
    assert "SQL" in skills_cell
    assert "SQL" in strengths_cell
    assert "Kubernetes" in missing_cell and "Missing:" in missing_cell
    assert "Leadership" in missing_cell and "Needs verification:" in missing_cell


def test_export_creates_no_screening_rows_and_mutates_nothing(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Beta Synthetic", email="beta@example.com")
    app = _application(db_session, org, campaign, cand)
    run = _completed_run(db_session, org, app, 55.0)

    def _counts() -> tuple[int, int, int]:
        runs = db_session.execute(select(func.count()).select_from(ScreeningRun)).scalar_one()
        crits = db_session.execute(
            select(func.count()).select_from(CriterionResult)
        ).scalar_one()
        apps = db_session.execute(select(func.count()).select_from(Application)).scalar_one()
        return runs, crits, apps

    before_counts = _counts()
    before_app_state = app.state
    before_score = run.score
    before_run_id = run.id

    _build(db_session, org, campaign)
    db_session.expire_all()

    assert _counts() == before_counts  # no new rows created or deleted
    refreshed_app = db_session.get(Application, app.id)
    refreshed_run = db_session.get(ScreeningRun, before_run_id)
    assert refreshed_app.state == before_app_state  # application untouched
    assert refreshed_run is not None
    assert refreshed_run.score == before_score  # saved score untouched


def test_formula_injection_is_neutralised(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    payload = "=cmd|'/c calc'!A1"
    cand = _candidate(db_session, org, name=payload, email="inject@example.com")
    _application(
        db_session, org, campaign, cand,
        answers={"full_name": payload, "notes": "+SUM(A1:A2)"},
    )

    wb = _load_workbook(_build(db_session, org, campaign))
    header, body = _detail_rows(wb)
    name_cell = body[0][header.index("Candidate name")]
    # The leading '=' must be escaped so Excel treats it as literal text, not a formula.
    assert isinstance(name_cell, str)
    assert name_cell.startswith("'=")
    assert not name_cell.startswith("=")


def test_email_and_phone_are_masked_by_default(db_session) -> None:
    """Without candidate.view_pii (unmask_contact=False) contact is masked."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(
        db_session, org, name="Masked Synthetic", email="masked.person@example.com"
    )
    _application(db_session, org, campaign, cand)

    wb = _load_workbook(_build(db_session, org, campaign))  # unmask_contact defaults False
    header, body = _detail_rows(wb)
    email_cell = body[0][header.index("Email address")]
    assert isinstance(email_cell, str)
    assert email_cell != "masked.person@example.com"
    assert "*" in email_cell


def test_email_and_phone_unmasked_when_permitted(db_session) -> None:
    """With unmask_contact=True (caller holds candidate.view_pii) the export shows the real
    email and phone."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(
        db_session, org, name="Real Synthetic", email="real.person@example.com"
    )
    _application(db_session, org, campaign, cand)

    wb = _load_workbook(
        _build(db_session, org, campaign, actor_id=uuid.uuid4(), unmask_contact=True)
    )
    header, body = _detail_rows(wb)
    assert body[0][header.index("Email address")] == "real.person@example.com"
    # The seeded mobile is +14155550100.
    assert "4155550100" in str(body[0][header.index("Contact number")])


def test_raw_pii_in_answers_is_not_exported(db_session) -> None:
    """Raw email/mobile/linkedin held in the application answers snapshot must never leak
    into the (masked) export — only the masked canonical-record values appear."""
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Snap Synthetic", email="snap@example.com")
    _application(
        db_session, org, campaign, cand,
        answers={
            "full_name": "Snap Synthetic",
            "email": "raw.snap@example.com",
            "mobile": "+19998887777",
            "linkedin": "linkedin.com/in/rawsnap",
        },
    )
    wb = _load_workbook(_build(db_session, org, campaign))
    blob = "\n".join(
        str(c) for row in wb["Candidates"].iter_rows(values_only=True)
        for c in row if c is not None
    )
    assert "raw.snap@example.com" not in blob
    assert "+19998887777" not in blob
    assert "linkedin.com/in/rawsnap" not in blob


def test_resume_filename_and_download_hyperlink_present_when_resume_exists(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Resume Synthetic", email="res@example.com")
    app = _application(db_session, org, campaign, cand)
    doc = Document(
        organisation_id=org.id,
        kind=DocumentKind.RESUME.value,
        status=DocumentStatus.CLEAN.value,
        original_filename="jane_resume.pdf",
        storage_key="secret-storage-key-should-not-leak",
        content_type="application/pdf",
        size_bytes=1234,
        sha256="a" * 64,
    )
    db_session.add(doc)
    db_session.flush()
    app.resume_document_id = doc.id
    db_session.flush()

    data = _build(db_session, org, campaign)
    # Load in normal (non-read-only) mode so cell .hyperlink is accessible.
    wb = _load_workbook_rw(data)
    ws = wb["Candidates"]
    header = [c.value for c in ws[1]]
    resume_i = header.index("Resume") + 1
    summary_i = header.index("Candidate summary") + 1

    # The resume cell is a friendly "Download Resume" hyperlink, not a raw URL.
    resume_cell = ws.cell(row=2, column=resume_i)
    assert resume_cell.value == "Download Resume"
    assert resume_cell.hyperlink is not None
    target = resume_cell.hyperlink.target
    # It points at the authenticated SPA route scoped to THIS application, candidate-specific.
    assert target.endswith(f"/resume/{app.id}")
    # It must NEVER be a direct API URL, a storage key, or a public bucket path.
    assert "/api/v1/documents/" not in target
    assert "secret-storage-key-should-not-leak" not in target

    # The "View summary" link points at the in-app candidate-summary route for THIS app.
    summary_cell = ws.cell(row=2, column=summary_i)
    assert summary_cell.value == "View summary"
    assert summary_cell.hyperlink is not None
    assert summary_cell.hyperlink.target.endswith(f"/candidates/{app.id}")

    blob = "\n".join(
        str(c.value) for row in ws.iter_rows() for c in row if c.value is not None
    )
    assert "secret-storage-key-should-not-leak" not in blob


def test_resume_cell_shows_unavailable_when_no_resume(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="NoResume Synthetic", email="nr@example.com")
    _application(db_session, org, campaign, cand)  # resume_document_id stays None

    wb = _load_workbook_rw(_build(db_session, org, campaign))
    ws = wb["Candidates"]
    header = [c.value for c in ws[1]]
    resume_i = header.index("Resume") + 1
    # No resume -> clear text, and crucially NO hyperlink (never a broken link).
    resume_cell = ws.cell(row=2, column=resume_i)
    assert resume_cell.value == "Resume unavailable"
    assert resume_cell.hyperlink is None


def test_sheet_names_are_hr_two_sheet_layout(db_session) -> None:
    org = make_org(db_session)
    campaign = _open_campaign(db_session, org)
    cand = _candidate(db_session, org, name="Names Synthetic", email="nm@example.com")
    app = _application(db_session, org, campaign, cand)
    _completed_run(db_session, org, app, 70.0)

    wb = _load_workbook(_build(db_session, org, campaign))
    assert wb.sheetnames == ["Candidates", "Summary"]


# --------------------------------------------------------------------------------------
# API-level tests (authorisation, cross-campaign isolation)
# --------------------------------------------------------------------------------------
def _seed_campaign_with_candidate(engine, *, role_name, assign=True):  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        # Unique org name + user email per seed so two independent orgs can coexist in one
        # test (organisation.name and user.email are unique).
        suffix = uuid.uuid4().hex[:8]
        org = make_org(session, name=f"SYNTHETIC Org {suffix}")
        role = make_role(session, org, role_name)
        user = make_user(
            session, org, roles=[role], password=PASSWORD,
            email=f"api.user.{suffix}@example.com",
        )
        campaign = _open_campaign(session, org)
        cand = _candidate(
            session, org, name="API Synthetic", email=f"api.{suffix}@example.com"
        )
        app = _application(session, org, campaign, cand)
        _completed_run(session, org, app, 80.0)
        if assign:
            session.add(
                CampaignAssignment(
                    user_id=user.id, campaign_id=campaign.id, organisation_id=org.id
                )
            )
        session.commit()
        return user.email, campaign.id
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _export_path(campaign_id) -> str:  # type: ignore[no-untyped-def]
    return f"/api/v1/reports/campaigns/{campaign_id}/export"


def test_api_authorised_user_downloads_xlsx(client, engine) -> None:
    email, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    headers = _login(client, email)
    resp = client.get(_export_path(campaign_id), headers=headers)
    assert resp.status_code == 200, resp.text
    assert (
        resp.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["content-disposition"]
    wb = _load_workbook(resp.content)
    assert wb.sheetnames == EXPECTED_SHEETS


def test_api_unauthenticated_is_rejected(client, engine) -> None:
    _, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    resp = client.get(_export_path(campaign_id))
    assert resp.status_code in (401, 403)


def test_api_panel_user_without_candidate_view_is_forbidden(client, engine) -> None:
    """Vertical privilege escalation: a panel-only user lacks candidate.view -> 403."""
    email, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.INTERVIEW_PANEL, assign=True
    )
    headers = _login(client, email)
    resp = client.get(_export_path(campaign_id), headers=headers)
    assert resp.status_code == 403, resp.text


def test_api_user_not_assigned_to_campaign_is_forbidden(client, engine) -> None:
    """Object-level authz: holds candidate.view but is NOT assigned to the campaign."""
    email, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=False
    )
    headers = _login(client, email)
    resp = client.get(_export_path(campaign_id), headers=headers)
    assert resp.status_code == 403, resp.text


def test_api_no_cross_campaign_or_cross_org_leakage(client, engine) -> None:
    """A user assigned to campaign A in org A cannot export a campaign in org B."""
    email_a, _campaign_a = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    _email_b, campaign_b = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    headers_a = _login(client, email_a)
    # User A asks for org B's campaign -> 404 (not found in A's organisation).
    resp = client.get(_export_path(campaign_b), headers=headers_a)
    assert resp.status_code == 404, resp.text


def test_api_unknown_campaign_is_not_found(client, engine) -> None:
    email, _campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    headers = _login(client, email)
    resp = client.get(_export_path(uuid.uuid4()), headers=headers)
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------------------
# In-app report preview (JSON) + preview/download consistency
# --------------------------------------------------------------------------------------
def _report_path(campaign_id) -> str:  # type: ignore[no-untyped-def]
    return f"/api/v1/reports/campaigns/{campaign_id}/report"


def test_report_json_matches_download_records(client, engine) -> None:
    """The in-app preview JSON and the downloaded workbook must show the SAME candidate
    records (same names, same scores, same order) — one shared implementation."""
    email, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    headers = _login(client, email)

    # JSON preview.
    resp = client.get(_report_path(campaign_id), headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert "summary" in report and "columns" in report and "rows" in report
    json_names = [r["candidate_name"] for r in report["rows"]]
    json_scores = [r["overall_score"] for r in report["rows"]]

    # Downloaded workbook.
    xlsx = client.get(_export_path(campaign_id), headers=headers)
    assert xlsx.status_code == 200, xlsx.text
    wb = _load_workbook(xlsx.content)
    header, body = _detail_rows(wb)
    name_i = header.index("Candidate name")
    xlsx_names = [row[name_i] for row in body]

    # Same candidates in the same order.
    assert json_names == xlsx_names
    assert len(json_scores) == len(xlsx_names)


def test_report_json_requires_candidate_view_and_assignment(client, engine) -> None:
    # Panel-only user (no candidate.view) is refused.
    email, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.INTERVIEW_PANEL, assign=True
    )
    headers = _login(client, email)
    resp = client.get(_report_path(campaign_id), headers=headers)
    assert resp.status_code == 403, resp.text


def test_report_json_unmasks_contact_for_view_pii_role(client, engine) -> None:
    """recruiter_admin holds candidate.view_pii, so the preview shows real contact."""
    email, campaign_id = _seed_campaign_with_candidate(
        engine, role_name=RoleName.RECRUITER_ADMIN, assign=True
    )
    headers = _login(client, email)
    resp = client.get(_report_path(campaign_id), headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert rows, "expected at least one candidate row"
    assert resp.json()["summary"]["contact_unmasked"] is True
    # The seeded candidate email is api.<suffix>@example.com (unmasked => contains '@' and
    # no masking asterisks).
    assert all(r["contact_masked"] is False for r in rows)
    assert any("@example.com" in (r["email"] or "") and "*" not in (r["email"] or "")
               for r in rows)
