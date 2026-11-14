"""API tests for the long-term automation features: notifications, SLA, offers, onboarding,
policies + assistant, interview confirmation links, candidate journey, feedback summary,
waitlist list, privacy requests list and the integrations registry. All data is synthetic."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.errors import ValidationError
from app.modules.applications.models import Application
from app.modules.assessments.models import Assessment
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.forms import service as form_service
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from app.modules.interviews.models import (
    InterviewAssignment,
    InterviewInvitation,
    InterviewSlot,
    InterviewStage,
)
from app.modules.notifications import templates
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
    "candidate_declaration": True,
    "privacy_consent": True,
}


def _factory(engine):  # type: ignore[no-untyped-def]
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _seed(engine):  # type: ignore[no-untyped-def]
    session = _factory(engine)()
    try:
        org = make_org(session)
        roles = {r: make_role(session, org, r) for r in RoleName}
        admin = make_user(session, org, roles=[roles[RoleName.RECRUITER_ADMIN]],
                          password=PASSWORD, email="admin@example.com")
        recruiter = make_user(session, org, roles=[roles[RoleName.RECRUITER]],
                              password=PASSWORD, email="recruiter@example.com")
        panel = make_user(session, org, roles=[roles[RoleName.INTERVIEW_PANEL]],
                          password=PASSWORD, email="panel@example.com")
        make_user(session, org, roles=[roles[RoleName.SYSTEM_ADMIN]],
                  password=PASSWORD, email="sysadmin@example.com")
        make_user(session, org, roles=[roles[RoleName.EMPLOYEE]],
                  password=PASSWORD, email="employee@example.com")
        campaign = Campaign(
            organisation_id=org.id, project_id=uuid.uuid4(), name="SYNTHETIC Campaign",
            position_title="Synthetic Engineer", number_of_openings=1,
            state=CampaignState.APPLICATIONS_OPEN.value, privacy_notice_version="v1",
        )
        session.add(campaign)
        session.flush()
        form = form_service.create_form_draft(
            session, organisation_id=org.id, campaign_id=campaign.id, actor_id=admin.id,
            compensation_enabled=False,
        )
        form_service.approve_form_version(
            session, organisation_id=org.id, form_version_id=form.id, actor_id=admin.id
        )
        campaign.approved_form_version_id = form.id
        for user in (admin, recruiter):
            session.add(CampaignAssignment(user_id=user.id, campaign_id=campaign.id,
                                           organisation_id=org.id))
        session.add(InterviewAssignment(
            organisation_id=org.id, campaign_id=campaign.id, stage_id=None,
            interviewer_id=panel.id, assigned_by=admin.id, is_active=True,
        ))
        session.commit()
        return {"org_id": org.id, "campaign_id": campaign.id, "admin_id": admin.id}
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _apply(client, campaign_id):  # type: ignore[no-untyped-def]
    resp = client.post(
        f"/api/v1/public/campaigns/{campaign_id}/apply",
        data={"answers": json.dumps(ANSWERS)},
        files={"resume": ("resume.txt", RESUME, "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["application_id"]


def _set_state(engine, application_id, state, *, hours_old=None):  # type: ignore[no-untyped-def]
    session = _factory(engine)()
    try:
        app = session.get(Application, uuid.UUID(application_id))
        app.state = state
        if hours_old is not None:
            app.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours_old)
        session.commit()
    finally:
        session.close()


@pytest.fixture
def world(client, engine):  # type: ignore[no-untyped-def]
    seeded = _seed(engine)
    application_id = _apply(client, seeded["campaign_id"])
    return {
        **seeded,
        "application_id": application_id,
        "admin": _login(client, "admin@example.com"),
        "recruiter": _login(client, "recruiter@example.com"),
        "panel": _login(client, "panel@example.com"),
        "sysadmin": _login(client, "sysadmin@example.com"),
        "employee": _login(client, "employee@example.com"),
    }


# ------------------------------------------------------------------ notifications


def test_channels_default_to_not_configured(client, world) -> None:
    body = client.get("/api/v1/notifications/status", headers=world["admin"]).json()
    assert body["email"]["state"] == "not_configured"
    assert body["whatsapp"]["state"] == "not_configured"


def test_message_is_recorded_honestly_when_no_provider(client, world) -> None:
    r = client.post(
        "/api/v1/notifications/send", headers=world["admin"],
        json={"application_id": world["application_id"], "template_key": "interview_reminder"},
    )
    assert r.status_code == 201, r.text
    delivery = r.json()
    assert delivery["status"] == "unconfigured"  # never "sent" without a provider
    assert delivery["manual_link"].startswith("mailto:")
    assert "Synthetic Candidate" in delivery["body"]
    log = client.get(
        f"/api/v1/notifications/deliveries?application_id={world['application_id']}",
        headers=world["admin"],
    ).json()
    assert len(log) == 1


def test_simulate_mode_is_labelled_simulated(client, world, test_settings) -> None:
    test_settings.notification_email_mode = "simulate"
    r = client.post(
        "/api/v1/notifications/send", headers=world["admin"],
        json={"application_id": world["application_id"], "template_key": "offer_followup"},
    )
    assert r.json()["status"] == "simulated"


def test_whatsapp_needs_a_mobile_and_stays_a_placeholder(client, world) -> None:
    r = client.post(
        "/api/v1/notifications/send", headers=world["admin"],
        json={"application_id": world["application_id"], "template_key": "interview_reminder",
              "channel": "whatsapp"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "unconfigured"
    assert r.json()["manual_link"].startswith("https://wa.me/")


def test_templates_never_accept_internal_scores() -> None:
    with pytest.raises(ValidationError):
        templates.render("Hello {{candidate_name}}", ("candidate_name",), {"score": "92"})
    assert templates.single_line("Hi\r\nBcc: x@evil.test") == "Hi Bcc: x@evil.test"


def test_template_edits_are_versioned_and_validated(client, world) -> None:
    ok = client.put(
        "/api/v1/notifications/templates/offer_followup", headers=world["admin"],
        json={"subject": "About your offer", "body": "Hello {{candidate_name}}, please reply."},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["version"] == 1 and ok.json()["is_built_in"] is False
    again = client.put(
        "/api/v1/notifications/templates/offer_followup", headers=world["admin"],
        json={"subject": "About your offer", "body": "Hi {{candidate_name}}, reply soon."},
    )
    assert again.json()["version"] == 2
    bad = client.put(
        "/api/v1/notifications/templates/offer_followup", headers=world["admin"],
        json={"subject": "x", "body": "Your score is {{score}}"},
    )
    assert bad.status_code == 422
    denied = client.put(
        "/api/v1/notifications/templates/offer_followup", headers=world["recruiter"],
        json={"subject": "x", "body": "y"},
    )
    assert denied.status_code == 403


# ------------------------------------------------------------------------ SLA


def test_sla_flags_at_risk_and_overdue_and_runs_once(client, engine, world) -> None:
    _set_state(engine, world["application_id"], "screened", hours_old=60)
    items = client.get("/api/v1/sla/applications", headers=world["admin"]).json()
    assert items[0]["status"] == "overdue"
    summary = client.get("/api/v1/sla/summary", headers=world["admin"]).json()
    assert summary["overdue"] == 1 and summary["window_hours"] == 48

    first = client.post("/api/v1/sla/run-check", headers=world["admin"]).json()
    assert first["overdue_recorded"] == 1
    second = client.post("/api/v1/sla/run-check", headers=world["admin"]).json()
    assert second["overdue_recorded"] == 0  # one notice per application and level

    _set_state(engine, world["application_id"], "screened", hours_old=40)
    assert client.get("/api/v1/sla/applications", headers=world["admin"]).json()[0][
        "status"
    ] == "at_risk"
    _set_state(engine, world["application_id"], "additional_info_requested", hours_old=100)
    assert client.get("/api/v1/sla/applications", headers=world["admin"]).json()[0][
        "status"
    ] == "paused"
    _set_state(engine, world["application_id"], "interview_recommended")
    assert client.get("/api/v1/sla/summary", headers=world["admin"]).json()["completed"] == 1


def test_sla_policy_needs_approver(client, world) -> None:
    body = {"window_hours": 24, "at_risk_percent": 50}
    denied = client.put("/api/v1/sla/policy", headers=world["recruiter"], json=body)
    assert denied.status_code == 403
    ok = client.put("/api/v1/sla/policy", headers=world["admin"], json=body)
    assert ok.status_code == 200 and ok.json()["window_hours"] == 24


# ------------------------------------------------------- offers and onboarding


def test_offer_requires_selection_and_follows_draft_approve_issue(client, engine, world) -> None:
    app_id = world["application_id"]
    early = client.post("/api/v1/offers", headers=world["admin"], json={"application_id": app_id})
    assert early.status_code == 422  # not selected yet

    _set_state(engine, app_id, "selected")
    offer = client.post("/api/v1/offers", headers=world["admin"], json={"application_id": app_id})
    assert offer.status_code == 201, offer.text
    offer_id = offer.json()["id"]
    assert offer.json()["status"] == "drafted"
    assert client.post("/api/v1/offers", headers=world["admin"],
                       json={"application_id": app_id}).status_code == 409

    # Cannot be issued before approval; a recruiter cannot approve.
    too_early = client.post(f"/api/v1/offers/{offer_id}/issue", headers=world["admin"])
    assert too_early.status_code == 409
    assert client.post(f"/api/v1/offers/{offer_id}/approve",
                       headers=world["recruiter"]).status_code == 403
    assert client.post(f"/api/v1/offers/{offer_id}/approve",
                       headers=world["admin"]).json()["status"] == "approved"
    issued = client.post(f"/api/v1/offers/{offer_id}/issue", headers=world["admin"]).json()
    assert issued["status"] == "issued"
    assert issued["delivery"]["status"] == "unconfigured"
    reminder = client.post(f"/api/v1/offers/{offer_id}/remind", headers=world["admin"])
    assert reminder.status_code == 200
    answered = client.post(f"/api/v1/offers/{offer_id}/respond", headers=world["admin"],
                           json={"outcome": "accepted"}).json()
    assert answered["status"] == "accepted"


def test_joining_case_checks_and_messages(client, engine, world) -> None:
    app_id = world["application_id"]
    assert client.post("/api/v1/onboarding/cases", headers=world["admin"],
                       json={"application_id": app_id}).status_code == 422
    _set_state(engine, app_id, "selected")
    created = client.post("/api/v1/onboarding/cases", headers=world["admin"],
                          json={"application_id": app_id})
    assert created.status_code == 201, created.text
    case_id = created.json()["case"]["id"]
    assert created.json()["delivery"]["template_key"] == "document_request"
    detail = client.get(f"/api/v1/onboarding/cases/{case_id}", headers=world["admin"]).json()
    assert len(detail["documents"]) == 7
    assert "not connected" in detail["ai_verification_note"]
    id_doc = next(d for d in detail["documents"] if d["name"] == "Government ID proof")

    # A document with a different name and an expiry date in the past.
    got = client.post(
        f"/api/v1/onboarding/cases/{case_id}/documents/{id_doc['id']}/receive",
        headers=world["admin"],
        json={"name_on_document": "Someone Else", "expiry_date": "2020-01-01"},
    )
    assert got.status_code == 200 and got.json()["status"] == "submitted"
    flags = client.post(f"/api/v1/onboarding/cases/{case_id}/verify",
                        headers=world["admin"]).json()
    kinds = {f["kind"] for f in flags}
    assert {"mismatch", "expired", "missing"} <= kinds

    # Flags never resolve themselves; HR resolves each with a reason.
    mismatch = next(f for f in flags if f["kind"] == "mismatch")
    resolved = client.post(
        f"/api/v1/onboarding/cases/{case_id}/flags/{mismatch['id']}/resolve",
        headers=world["admin"], json={"action": "accepted", "reason": "Maiden name, checked"},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "accepted"
    rerun = client.post(f"/api/v1/onboarding/cases/{case_id}/verify", headers=world["admin"]).json()
    assert sum(1 for f in rerun if f["kind"] == "mismatch" and f["status"] == "open") == 0

    # Joining messages need a date, then HR approval of the wording.
    assert client.post(f"/api/v1/onboarding/cases/{case_id}/send-prejoining",
                       headers=world["admin"]).status_code == 422
    assert client.post(f"/api/v1/onboarding/cases/{case_id}/approve-content",
                       headers=world["admin"]).status_code == 422
    patched = client.patch(
        f"/api/v1/onboarding/cases/{case_id}", headers=world["admin"],
        json={"joining_date": "2026-12-01", "reporting_manager": "A. Manager",
              "department": "Engineering"},
    )
    assert patched.status_code == 200 and patched.json()["content_approved"] is False
    assert client.post(f"/api/v1/onboarding/cases/{case_id}/approve-content",
                       headers=world["admin"]).json()["content_approved"] is True
    pre = client.post(f"/api/v1/onboarding/cases/{case_id}/send-prejoining", headers=world["admin"])
    assert pre.status_code == 200 and "A. Manager" in pre.json()["body"]
    no_consent = client.post(
        f"/api/v1/onboarding/cases/{case_id}/send-announcement", headers=world["admin"],
        json={"recipients": ["team@example.com"], "joiner_agreed": False},
    )
    assert no_consent.status_code == 422
    sent = client.post(
        f"/api/v1/onboarding/cases/{case_id}/send-announcement", headers=world["admin"],
        json={"recipients": ["team@example.com"], "joiner_agreed": True},
    )
    assert sent.status_code == 200 and len(sent.json()["deliveries"]) == 1

    preview = client.get(f"/api/v1/onboarding/cases/{case_id}/hrms-preview",
                         headers=world["admin"]).json()
    assert preview["state"] == "not_configured"
    assert preview["record"]["department"] == "Engineering"
    assert "email" not in preview["record"] or preview["record"].get("work_email") is None


# ------------------------------------------------------------ policies + assistant


def test_policy_library_and_assistant_answer_only_from_approved_text(client, world) -> None:
    created = client.post(
        "/api/v1/policies", headers=world["admin"],
        json={"title": "Leave policy", "publish": False,  # draft first, publish below
              "body": "Employees receive 20 days of paid annual leave each year. "
                      "Unused leave can be carried forward up to 5 days."},
    )
    assert created.status_code == 201, created.text
    policy_id = created.json()["id"]

    # Draft text is not used to answer questions, and employees cannot see drafts.
    before = client.post("/api/v1/assistant/ask", headers=world["employee"],
                         json={"question": "How many days of annual leave do I get?"}).json()
    assert before["answered"] is False and before["route_to_hr"] is True
    assert client.get("/api/v1/policies", headers=world["employee"]).json() == []

    assert client.post(f"/api/v1/policies/{policy_id}/approve",
                       headers=world["recruiter"]).status_code == 403
    approved = client.post(f"/api/v1/policies/{policy_id}/approve", headers=world["admin"])
    assert approved.json()["status"] == "approved"

    after = client.post("/api/v1/assistant/ask", headers=world["employee"],
                        json={"question": "How many days of annual leave do I get?"}).json()
    assert after["answered"] is True
    assert "20 days" in after["answer"]
    assert after["sources"][0]["title"] == "Leave policy"

    holiday = client.post("/api/v1/assistant/ask", headers=world["employee"],
                          json={"question": "When is the next holiday?"}).json()
    assert holiday["answered"] is False and "not set up" in holiday["answer"]

    ack = client.post(f"/api/v1/policies/{policy_id}/acknowledge", headers=world["employee"])
    assert ack.status_code == 200 and ack.json()["acknowledged"] is True

    # An approved policy is never edited in place: revise, then approve the new version.
    assert client.put(f"/api/v1/policies/{policy_id}", headers=world["admin"],
                      json={"body": "x"}).status_code == 409
    revised = client.post(f"/api/v1/policies/{policy_id}/revise", headers=world["admin"])
    assert revised.status_code == 201 and revised.json()["version"] == 2
    new_id = revised.json()["id"]
    client.post(f"/api/v1/policies/{new_id}/approve", headers=world["admin"])
    listing = client.get("/api/v1/policies", headers=world["admin"]).json()
    statuses = {(p["version"], p["status"]) for p in listing}
    assert statuses == {(1, "retired"), (2, "approved")}

    unanswered = client.get("/api/v1/assistant/unanswered", headers=world["admin"]).json()
    assert any("holiday" in q["question"].lower() for q in unanswered)
    assert client.get("/api/v1/assistant/unanswered",
                      headers=world["employee"]).status_code == 403


# ------------------------------------------------------ interview confirmations


def _make_invitation(engine, world):  # type: ignore[no-untyped-def]
    session = _factory(engine)()
    try:
        stage = InterviewStage(organisation_id=world["org_id"], campaign_id=world["campaign_id"],
                               name="Technical", sequence=1)
        session.add(stage)
        session.flush()
        slot = InterviewSlot(
            stage_id=stage.id, organisation_id=world["org_id"],
            slot_date=dt.date.today() + dt.timedelta(days=3), start_time="10:00",
            location="Head office", mode="in_person", capacity=2, confirmed_count=0,
        )
        session.add(slot)
        invitation = InterviewInvitation(
            organisation_id=world["org_id"], application_id=uuid.UUID(world["application_id"]),
            campaign_id=world["campaign_id"], status="invited", attendance="pending",
            approved_by=world["admin_id"], invited_at=dt.datetime.now(dt.UTC),
        )
        session.add(invitation)
        session.commit()
        return invitation.id, slot.id
    finally:
        session.close()


def test_candidate_reply_link_notifies_interviewer_and_works_once(client, engine, world) -> None:
    invitation_id, slot_id = _make_invitation(engine, world)
    issued = client.post(
        f"/api/v1/interview-confirmations/invitations/{invitation_id}/link", headers=world["admin"]
    )
    assert issued.status_code == 201, issued.text
    url = issued.json()["url"]
    token = url.rsplit("/", 1)[1]
    assert issued.json()["delivery"]["status"] == "unconfigured"
    assert url in issued.json()["delivery"]["body"]

    preview = client.get(f"/api/v1/interview-confirmations/public/{token}").json()
    assert preview["state"] == "open" and preview["first_name"] == "Synthetic"
    assert "Candidate" not in preview["first_name"]  # first name only
    assert client.get("/api/v1/interview-confirmations/public/not-a-token").status_code == 404

    reply = client.post(f"/api/v1/interview-confirmations/public/{token}/respond",
                        json={"response": "reschedule_requested"})
    assert reply.status_code == 200, reply.text
    again = client.post(f"/api/v1/interview-confirmations/public/{token}/respond",
                        json={"response": "confirmed"})
    assert again.status_code == 409

    status = client.get(f"/api/v1/interview-confirmations/invitations/{invitation_id}/status",
                        headers=world["admin"]).json()
    assert status["state"] == "answered" and status["invitation_status"] == "reschedule_requested"
    log = client.get(
        f"/api/v1/notifications/deliveries?campaign_id={world['campaign_id']}",
        headers=world["admin"],
    ).json()
    notices = [d for d in log if d["template_key"] == "interviewer_confirmation_notice"]
    assert len(notices) == 1 and notices[0]["recipient"] == "panel@example.com"

    slots = client.get(
        f"/api/v1/interview-confirmations/invitations/{invitation_id}/suggested-slots",
        headers=world["admin"],
    ).json()
    assert slots and slots[0]["slot_id"] == str(slot_id) and slots[0]["remaining"] == 2


def test_link_works_after_hr_booked_slot_and_decline_frees_it(client, engine, world) -> None:
    invitation_id, slot_id = _make_invitation(engine, world)
    session = _factory(engine)()
    try:
        inv = session.get(InterviewInvitation, invitation_id)
        slot = session.get(InterviewSlot, slot_id)
        inv.slot_id, inv.status, slot.confirmed_count = slot.id, "confirmed", 1
        session.commit()
    finally:
        session.close()
    issued = client.post(
        f"/api/v1/interview-confirmations/invitations/{invitation_id}/link", headers=world["admin"]
    )
    assert issued.status_code == 201, issued.text
    token = issued.json()["url"].rsplit("/", 1)[1]
    assert client.get(f"/api/v1/interview-confirmations/public/{token}").json()["when"] != (
        "to be confirmed"
    )
    client.post(f"/api/v1/interview-confirmations/public/{token}/respond",
                json={"response": "declined"})
    session = _factory(engine)()
    try:
        assert session.get(InterviewSlot, slot_id).confirmed_count == 0
        assert session.get(InterviewInvitation, invitation_id).status == "declined"
    finally:
        session.close()


def test_expired_link_is_refused(client, engine, world) -> None:
    invitation_id, _ = _make_invitation(engine, world)
    token = client.post(
        f"/api/v1/interview-confirmations/invitations/{invitation_id}/link?send=false",
        headers=world["admin"],
    ).json()["url"].rsplit("/", 1)[1]
    from app.modules.interview_confirmations.models import InterviewConfirmationLink

    session = _factory(engine)()
    try:
        for link in session.query(InterviewConfirmationLink).all():
            link.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
        session.commit()
    finally:
        session.close()
    r = client.post(f"/api/v1/interview-confirmations/public/{token}/respond",
                    json={"response": "confirmed"})
    assert r.status_code == 404


# ------------------------------------------------------------------- journey etc.


def test_journey_follows_the_application(client, engine, world) -> None:
    app_id = world["application_id"]
    fresh = client.get(f"/api/v1/journey/applications/{app_id}", headers=world["admin"]).json()
    keys = [s["key"] for s in fresh["stages"]]
    assert keys == [
        "applied", "resume_checked", "screened", "hr_review", "pre_screening",
        "interview_invited", "interview_confirmed", "interview_done", "decision",
        "offer", "documents", "joining",
    ]
    assert fresh["stages"][0]["status"] == "done" and fresh["closed"] is False

    _set_state(engine, app_id, "selected")
    selected = client.get(f"/api/v1/journey/applications/{app_id}", headers=world["admin"]).json()
    by_key = {s["key"]: s for s in selected["stages"]}
    assert by_key["decision"]["status"] == "done" and by_key["decision"]["detail"] == "Selected"
    assert selected["current_stage"] == "offer"

    _set_state(engine, app_id, "rejected")
    closed = client.get(f"/api/v1/journey/applications/{app_id}", headers=world["admin"]).json()
    assert closed["closed"] is True
    assert {s["key"]: s for s in closed["stages"]}["offer"]["status"] == "skipped"

    # The panel cannot read the journey (it holds no candidate.view).
    assert client.get(f"/api/v1/journey/applications/{app_id}",
                      headers=world["panel"]).status_code == 403


def test_feedback_summary_gathers_what_interviewers_wrote(client, engine, world) -> None:
    session = _factory(engine)()
    try:
        for score, rec in ((4, "proceed"), (2, "hold")):
            session.add(Assessment(
                organisation_id=world["org_id"],
                application_id=uuid.UUID(world["application_id"]),
                campaign_id=world["campaign_id"], panel_member_id=uuid.uuid4(),
                criteria_scores={"technical": score}, recommendation=rec,
                interview_notes=f"note {score}", conflict_declared=False,
            ))
        session.commit()
    finally:
        session.close()
    body = client.get(f"/api/v1/assessments/summary/{world['application_id']}",
                      headers=world["admin"]).json()
    assert body["assessments_count"] == 2 and body["agreement"] == "mixed"
    assert body["criteria"][0]["average"] == 3.0
    assert body["ai_summary_state"] == "not_configured"
    assert "advisory" in body["advisory_note"]
    assert client.get(f"/api/v1/assessments/summary/{world['application_id']}",
                      headers=world["panel"]).status_code == 403


def test_waitlist_and_privacy_lists(client, world) -> None:
    added = client.post(
        "/api/v1/waitlist", headers=world["admin"],
        json={"application_id": world["application_id"], "reason": "Strong profile"},
    )
    assert added.status_code == 201, added.text
    rows = client.get(f"/api/v1/waitlist?campaign_id={world['campaign_id']}",
                      headers=world["admin"]).json()
    assert rows[0]["candidate_name"] == "Synthetic Candidate"

    created = client.post("/api/v1/privacy/requests", headers=world["sysadmin"],
                          json={"candidate_email": "cand@example.com",
                                "request_type": "access_export"})
    assert created.status_code == 201, created.text
    listing = client.get("/api/v1/privacy/requests", headers=world["sysadmin"]).json()
    assert listing[0]["candidate_email_masked"] == "c***@example.com"
    missing = client.post("/api/v1/privacy/requests", headers=world["sysadmin"],
                          json={"candidate_email": "nobody@example.com",
                                "request_type": "access_export"})
    assert missing.status_code == 404


def test_staff_only_lists_refuse_people_without_permission(client, world) -> None:
    # An employee holds only induction.view: every staff list must refuse, not return [].
    for path in (
        "/api/v1/offers",
        "/api/v1/onboarding/cases",
        "/api/v1/sla/summary",
        "/api/v1/sla/applications",
        "/api/v1/notifications/templates",
    ):
        assert client.get(path, headers=world["employee"]).status_code == 403, path
    # The panel member has assessment.submit only.
    assert client.get("/api/v1/offers", headers=world["panel"]).status_code == 403
    # Open to every signed-in person: the policy library and the assistant.
    assert client.get("/api/v1/policies", headers=world["employee"]).status_code == 200


def test_integrations_registry_is_honest(client, world) -> None:
    rows = {r["key"]: r for r in client.get("/api/v1/integrations",
                                            headers=world["admin"]).json()}
    assert rows["email"]["state"] == "not_configured"
    assert rows["zinghr"]["state"] == "planned"
    assert rows["whatsapp"]["needs"]
    assert client.get("/api/v1/integrations").status_code == 401
