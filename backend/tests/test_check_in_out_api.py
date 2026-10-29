"""API integration tests for the Check In / Check Out workflow, resume download, assessment
retrieval, and salary field serialization + role-based access. All data is synthetic."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import sessionmaker

from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.forms import service as form_service
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.interviews import service as interview_service
from app.modules.interviews.models import InterviewAssignment
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"
RESUME = b"email: cand@example.com\n5 years of experience in Python\n"

ANSWERS = {
    "full_name": "Synthetic Candidate",
    "email": "cand@example.com",
    "mobile": "+14155550100",
    "current_location": "Mumbai",
    "total_experience_years": "5",
    "notice_period": "30 days",
    "skills": "Python",
    "education": "BSc",
    # Compensation fields (collected because the form enables compensation below).
    "current_ctc": 1800000,
    "current_in_hand": 125000,
    "expected_ctc": 2200000,
    "candidate_declaration": True,
    "privacy_consent": True,
}


def _seed(engine, *, compensation=True):  # type: ignore[no-untyped-def]
    """Org + recruiter-admin + interview-panel users + an open campaign with an approved
    (optionally compensation-enabled) form. Returns identifiers used by the tests."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        org = make_org(session)
        admin_role = make_role(session, org, RoleName.RECRUITER_ADMIN)
        panel_role = make_role(session, org, RoleName.INTERVIEW_PANEL)
        admin = make_user(session, org, roles=[admin_role], password=PASSWORD,
                          email="admin@example.com")
        panel = make_user(session, org, roles=[panel_role], password=PASSWORD,
                          email="panel@example.com")

        campaign = Campaign(
            organisation_id=org.id, project_id=uuid.uuid4(),
            name="SYNTHETIC Campaign", position_title="Synthetic Engineer",
            number_of_openings=1, state=CampaignState.APPLICATIONS_OPEN.value,
            privacy_notice_version="v1",
        )
        session.add(campaign)
        session.flush()

        form = form_service.create_form_draft(
            session, organisation_id=org.id, campaign_id=campaign.id, actor_id=admin.id,
            compensation_enabled=compensation,
        )
        form_service.approve_form_version(
            session, organisation_id=org.id, form_version_id=form.id, actor_id=admin.id
        )
        campaign.approved_form_version_id = form.id
        session.add(CampaignAssignment(user_id=admin.id, campaign_id=campaign.id,
                                       organisation_id=org.id))
        # The panel member is assigned as an interviewer for this campaign (required for the
        # interview panel to access candidates since interviewer-assignment isolation).
        session.add(InterviewAssignment(
            organisation_id=org.id, campaign_id=campaign.id, stage_id=None,
            interviewer_id=panel.id, assigned_by=admin.id, is_active=True,
        ))
        session.commit()
        return {
            "org_id": org.id, "campaign_id": campaign.id, "panel_id": panel.id,
            "admin_id": admin.id,
            "admin_email": admin.email, "panel_email": panel.email,
        }
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _apply(client, campaign_id):  # type: ignore[no-untyped-def]
    resp = client.post(
        f"/api/v1/public/campaigns/{campaign_id}/apply",
        data={"answers": json.dumps(ANSWERS)},
        files={"resume": ("resume.txt", RESUME, "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["application_id"]


def _drive_to_scheduled(engine, application_id, campaign_id, admin_email):  # type: ignore[no-untyped-def]
    """Approve + schedule the application so it reaches INTERVIEW_SCHEDULED, returning the
    invitation id. Uses the service layer directly (the same path the UI drives)."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        from app.modules.identity.models import User

        admin = session.query(User).filter(User.email == admin_email).one()
        actor = AuthenticatedActor(
            user_id=admin.id, organisation_id=admin.organisation_id, email=admin.email,
            role_names=[RoleName.RECRUITER_ADMIN.value],
            permissions={"interview.approve", "interview.schedule", "assessment.submit",
                         "candidate.view"},
            assigned_campaign_ids={campaign_id},
        )
        app = session.get(Application, uuid.UUID(application_id))
        # Move to a screenable state so an interview can be approved.
        app.state = ApplicationState.SCREENED.value
        session.flush()
        inv = interview_service.record_walk_in_interview(session, actor=actor, application=app)
        session.commit()
        return inv.id
    finally:
        session.close()


def test_check_in_check_out_endpoints_full_flow(client, engine) -> None:
    s = _seed(engine)
    application_id = _apply(client, s["campaign_id"])
    invitation_id = _drive_to_scheduled(engine, application_id, s["campaign_id"], s["admin_email"])

    panel = _login(client, s["panel_email"])

    # Check in.
    r = client.post(f"/api/v1/interviews/invitations/{invitation_id}/check-in", headers=panel)
    assert r.status_code == 200, r.text
    assert r.json()["attendance"] == "checked_in"
    assert r.json()["checked_in_at"] is not None

    # Duplicate check-in rejected.
    r = client.post(f"/api/v1/interviews/invitations/{invitation_id}/check-in", headers=panel)
    assert r.status_code == 409, r.text

    # Cannot check out before the assessment is submitted.
    r = client.post(f"/api/v1/interviews/invitations/{invitation_id}/check-out", headers=panel)
    assert r.status_code == 409, r.text

    # Submit assessment.
    r = client.post("/api/v1/assessments", headers=panel, json={
        "application_id": application_id,
        "recommendation": "proceed",
        "criteria_scores": {"technical": 4},
    })
    assert r.status_code == 201, r.text

    # Retrieve the saved assessment (rehydration).
    r = client.get(f"/api/v1/assessments/by-application/{application_id}", headers=panel)
    assert r.status_code == 200, r.text
    assert r.json()["recommendation"] == "proceed"
    assert r.json()["criteria_scores"]["technical"] == 4

    # Now check out.
    r = client.post(f"/api/v1/interviews/invitations/{invitation_id}/check-out", headers=panel)
    assert r.status_code == 200, r.text
    assert r.json()["attendance"] == "checked_out"
    assert r.json()["checked_out_at"] is not None

    # Recruiter Admin can see the completed (checked_out) state on the application.
    admin = _login(client, s["admin_email"])
    r = client.get(f"/api/v1/applications/{application_id}", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == ApplicationState.CHECKED_OUT.value

    # Regression: a CHECKED_OUT candidate MUST appear in the Hiring Decisions inbox (the
    # check-in/out flow ends at CHECKED_OUT, not ASSESSED). Before the fix the inbox only
    # queried ASSESSED, so checked-out candidates silently vanished from the tab.
    r = client.get("/api/v1/decisions/pending", headers=admin)
    assert r.status_code == 200, r.text
    pending_ids = [row["application_id"] for row in r.json()]
    assert application_id in pending_ids, "checked-out candidate missing from decisions inbox"

    # And a decision can actually be recorded from the CHECKED_OUT state.
    r = client.post(
        "/api/v1/decisions",
        headers=admin,
        json={
            "application_id": application_id,
            "decision_type": "select",
            "reason": "Strong interview; proceed to offer.",
        },
    )
    assert r.status_code in (200, 201), r.text
    r = client.get(f"/api/v1/applications/{application_id}", headers=admin)
    assert r.json()["state"] == ApplicationState.SELECTED.value


def test_salary_fields_present_in_application_answers(client, engine) -> None:
    s = _seed(engine, compensation=True)
    application_id = _apply(client, s["campaign_id"])
    admin = _login(client, s["admin_email"])
    r = client.get(f"/api/v1/applications/{application_id}", headers=admin)
    assert r.status_code == 200, r.text
    answers = r.json()["answers"]
    # The salary fields the candidate submitted are serialized back to Recruiter Admin.
    assert answers["current_ctc"] == 1800000
    assert answers["current_in_hand"] == 125000
    assert answers["expected_ctc"] == 2200000


def test_resume_download_requires_candidate_view_and_returns_file(client, engine) -> None:
    s = _seed(engine)
    application_id = _apply(client, s["campaign_id"])

    # Recruiter Admin (candidate.view + assigned) can download the resume.
    admin = _login(client, s["admin_email"])
    r = client.get(f"/api/v1/documents/applications/{application_id}/resume", headers=admin)
    assert r.status_code == 200, r.text
    assert r.content == RESUME
    assert r.headers["content-disposition"].startswith("attachment")

    # A panel member (no candidate.view, not campaign-assigned) is refused the file.
    panel = _login(client, s["panel_email"])
    r = client.get(f"/api/v1/documents/applications/{application_id}/resume", headers=panel)
    assert r.status_code == 403, r.text


def test_resume_download_404_when_no_resume(client, engine) -> None:
    """An application with no resume document returns 404 so the UI shows a clear message."""
    s = _seed(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        app = Application(
            organisation_id=s["org_id"], campaign_id=s["campaign_id"],
            candidate_id=uuid.uuid4(), form_version_id=uuid.uuid4(),
            answers={"full_name": "No Resume"}, state=ApplicationState.SCREENED.value,
            resume_document_id=None,
        )
        session.add(app)
        session.commit()
        app_id = str(app.id)
    finally:
        session.close()

    admin = _login(client, s["admin_email"])
    r = client.get(f"/api/v1/documents/applications/{app_id}/resume", headers=admin)
    assert r.status_code == 404, r.text


def test_panel_can_read_interview_context_for_checked_in_candidate(client, engine) -> None:
    """An interview-panel member (assessment.submit only, NOT candidate.view) who IS
    assigned to the campaign can read the resume, the application, and the extracted fields
    for a candidate they are actively interviewing (application scheduled/checked in). This
    is the narrow grant that makes the panel's Resume and Application Form tabs work, now
    additionally gated by an active interviewer assignment to the candidate's campaign."""
    s = _seed(engine)
    application_id = _apply(client, s["campaign_id"])
    invitation_id = _drive_to_scheduled(engine, application_id, s["campaign_id"], s["admin_email"])
    panel = _login(client, s["panel_email"])

    # Scheduled (pre check-in) is already an interview-lifecycle state -> panel may read.
    r = client.get(f"/api/v1/documents/applications/{application_id}/resume", headers=panel)
    assert r.status_code == 200, r.text
    assert r.content == RESUME

    r = client.get(f"/api/v1/applications/{application_id}", headers=panel)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == application_id

    r = client.get(f"/api/v1/applications/{application_id}/extracted-fields", headers=panel)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    # Check the candidate in; still in the interview lifecycle -> still readable.
    r = client.post(f"/api/v1/interviews/invitations/{invitation_id}/check-in", headers=panel)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/documents/applications/{application_id}/resume", headers=panel)
    assert r.status_code == 200, r.text


def test_panel_cannot_read_context_for_candidate_not_in_interview(client, engine) -> None:
    """A panel member is refused the resume/application for a candidate who is NOT in the
    interview lifecycle (e.g. still being screened). The panel grant is scoped strictly to
    candidates they are actively interviewing; it does not widen to all candidates."""
    s = _seed(engine)
    application_id = _apply(client, s["campaign_id"])  # lands in extraction/screened, not interview
    panel = _login(client, s["panel_email"])

    r = client.get(f"/api/v1/documents/applications/{application_id}/resume", headers=panel)
    assert r.status_code == 403, r.text
    r = client.get(f"/api/v1/applications/{application_id}", headers=panel)
    assert r.status_code == 403, r.text
    r = client.get(f"/api/v1/applications/{application_id}/extracted-fields", headers=panel)
    assert r.status_code == 403, r.text
