"""API-level tests for interviewer-assignment management + panel isolation.

Exercises the real HTTP endpoints and authorisation: System Admin assignment-only access,
Recruiter Admin campaign-scoped management, interviewer IDOR protection, and that assignment
management never exposes candidate content. All data is synthetic.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import sessionmaker

from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from app.modules.interviews.models import InterviewInvitation
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"


def _seed(engine):  # type: ignore[no-untyped-def]
    """Org with system-admin, recruiter-admin (assigned to net campaign), recruiter, and two
    panel members, plus three campaigns (net/ai) with a scheduled candidate each."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        org = make_org(session)
        sysadmin = make_user(
            session, org, roles=[make_role(session, org, RoleName.SYSTEM_ADMIN)],
            password=PASSWORD, email="sysadmin@example.com",
        )
        radmin = make_user(
            session, org, roles=[make_role(session, org, RoleName.RECRUITER_ADMIN)],
            password=PASSWORD, email="radmin@example.com",
        )
        recruiter = make_user(
            session, org, roles=[make_role(session, org, RoleName.RECRUITER)],
            password=PASSWORD, email="recruiter@example.com",
        )
        panel_role = make_role(session, org, RoleName.INTERVIEW_PANEL)
        panel1 = make_user(session, org, roles=[panel_role], password=PASSWORD,
                           email="panel1@example.com")
        panel2 = make_user(session, org, roles=[panel_role], password=PASSWORD,
                           email="panel2@example.com")

        def _camp(title: str) -> Campaign:
            c = Campaign(
                organisation_id=org.id, project_id=uuid.uuid4(), name=title,
                position_title=title, number_of_openings=1,
                state=CampaignState.APPLICATIONS_OPEN.value, privacy_notice_version="v1",
            )
            session.add(c)
            session.flush()
            return c

        net = _camp("Network Security Operations")
        ai = _camp("AI Engineer")

        # Recruiter Admin manages the NET campaign only.
        session.add(CampaignAssignment(user_id=radmin.id, campaign_id=net.id,
                                       organisation_id=org.id))

        def _scheduled(campaign: Campaign, name: str) -> Application:
            import datetime as dt
            app = Application(
                organisation_id=org.id, campaign_id=campaign.id, candidate_id=uuid.uuid4(),
                form_version_id=uuid.uuid4(), answers={"full_name": name},
                state=ApplicationState.INTERVIEW_SCHEDULED.value,
            )
            session.add(app)
            session.flush()
            session.add(InterviewInvitation(
                organisation_id=org.id, application_id=app.id, campaign_id=campaign.id,
                stage_id=None, status="confirmed", attendance="pending",
                approved_by=radmin.id, invited_at=dt.datetime.now(tz=dt.UTC),
                auto_invite=False,
            ))
            session.flush()
            return app

        net_app = _scheduled(net, "Net Candidate")
        ai_app = _scheduled(ai, "AI Candidate")

        session.commit()
        return {
            "org_id": org.id, "net_id": net.id, "ai_id": ai.id,
            "net_app_id": str(net_app.id), "ai_app_id": str(ai_app.id),
            "sysadmin": sysadmin.email, "radmin": radmin.email,
            "recruiter": recruiter.email,
            "panel1_email": panel1.email, "panel1_id": str(panel1.id),
            "panel2_email": panel2.email, "panel2_id": str(panel2.id),
        }
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --------------------------------------------------------------------------------------
# 10: System Admin can create, view, and remove assignments
# --------------------------------------------------------------------------------------
def test_system_admin_can_manage_assignments(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])

    # Create.
    r = client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        headers=sys, json={"interviewer_id": s["panel1_id"]},
    )
    assert r.status_code == 201, r.text
    assignment_id = r.json()["id"]
    assert r.json()["interviewer_id"] == s["panel1_id"]
    assert r.json()["is_active"] is True
    # Response is metadata only — no candidate content.
    assert "candidate_name" not in r.json() and "answers" not in r.json()

    # List.
    r = client.get(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments", headers=sys
    )
    assert r.status_code == 200, r.text
    assert any(a["id"] == assignment_id for a in r.json())

    # Remove (soft).
    r = client.delete(f"/api/v1/interviews/assignments/{assignment_id}", headers=sys)
    assert r.status_code == 204, r.text
    r = client.get(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments", headers=sys
    )
    assert all(a["id"] != assignment_id for a in r.json())  # inactive hidden from the list


# --------------------------------------------------------------------------------------
# 11: System Admin cannot reach candidate content through this feature
# --------------------------------------------------------------------------------------
def test_system_admin_cannot_access_candidate_content(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])

    # No candidate.view: application + resume + extracted fields + assessments are refused.
    r = client.get(f"/api/v1/applications/{s['net_app_id']}", headers=sys)
    assert r.status_code == 403, r.text
    r = client.get(f"/api/v1/documents/applications/{s['net_app_id']}/resume", headers=sys)
    assert r.status_code == 403, r.text
    r = client.get(f"/api/v1/applications/{s['net_app_id']}/extracted-fields", headers=sys)
    assert r.status_code == 403, r.text
    # No assessment.submit: the panel worklist is refused.
    r = client.get("/api/v1/assessments/panel", headers=sys)
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------------------
# 12: Recruiter Admin cannot manage assignments outside their campaign scope
# --------------------------------------------------------------------------------------
def test_recruiter_admin_scoped_to_assigned_campaign(client, engine) -> None:
    s = _seed(engine)
    radmin = _login(client, s["radmin"])

    # Can manage the campaign they are assigned to (net).
    r = client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        headers=radmin, json={"interviewer_id": s["panel1_id"]},
    )
    assert r.status_code == 201, r.text

    # Cannot manage a campaign they are NOT assigned to (ai).
    r = client.post(
        f"/api/v1/interviews/campaigns/{s['ai_id']}/assignments",
        headers=radmin, json={"interviewer_id": s["panel1_id"]},
    )
    assert r.status_code == 403, r.text


def test_recruiter_without_assign_permission_denied(client, engine) -> None:
    s = _seed(engine)
    rec = _login(client, s["recruiter"])
    r = client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        headers=rec, json={"interviewer_id": s["panel1_id"]},
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------------------
# 2 + 8: interviewer panel is filtered; my-assignments drives buckets
# --------------------------------------------------------------------------------------
def test_interviewer_panel_and_my_assignments_are_scoped(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])
    # Assign panel1 to NET only.
    client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        headers=sys, json={"interviewer_id": s["panel1_id"]},
    )

    panel1 = _login(client, s["panel1_email"])
    # my-assignments -> exactly the NET bucket (keyed by campaign id).
    r = client.get("/api/v1/interviews/my-assignments", headers=panel1)
    assert r.status_code == 200, r.text
    assert [a["campaign_id"] for a in r.json()] == [str(s["net_id"])]

    # Panel worklist shows the NET candidate only.
    r = client.get("/api/v1/assessments/panel", headers=panel1)
    assert r.status_code == 200, r.text
    camps = {row["campaign_id"] for row in r.json()["interviews"]}
    assert camps == {str(s["net_id"])}

    # A panel member with NO assignment sees an empty worklist.
    panel2 = _login(client, s["panel2_email"])
    r = client.get("/api/v1/assessments/panel", headers=panel2)
    assert r.status_code == 200, r.text
    assert r.json()["interviews"] == []
    assert r.json()["total"] == 0


# --------------------------------------------------------------------------------------
# 8 (IDOR): direct API with another campaign's application id is denied
# --------------------------------------------------------------------------------------
def test_interviewer_cannot_act_on_unassigned_application_via_direct_api(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])
    # panel1 assigned to NET only.
    client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        headers=sys, json={"interviewer_id": s["panel1_id"]},
    )
    panel1 = _login(client, s["panel1_email"])

    # Forging the AI campaign's application id in the resume/application/assessment calls.
    r = client.get(f"/api/v1/applications/{s['ai_app_id']}", headers=panel1)
    assert r.status_code == 403, r.text
    r = client.get(f"/api/v1/documents/applications/{s['ai_app_id']}/resume", headers=panel1)
    assert r.status_code == 403, r.text
    r = client.post("/api/v1/assessments", headers=panel1, json={
        "application_id": s["ai_app_id"], "recommendation": "proceed",
        "criteria_scores": {"technical": 4},
    })
    assert r.status_code == 403, r.text

    # But the NET application (assigned) IS reachable for reads.
    r = client.get(f"/api/v1/applications/{s['net_app_id']}", headers=panel1)
    assert r.status_code == 200, r.text


def test_unauthenticated_cannot_manage_assignments(client, engine) -> None:
    s = _seed(engine)
    r = client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        json={"interviewer_id": s["panel1_id"]},
    )
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------------------
# Issue 1 root cause: GET /users must return role_names so the interviewer dropdown can
# filter to Interview Panel members.
# --------------------------------------------------------------------------------------
def test_users_list_includes_role_names(client, engine) -> None:
    s = _seed(engine)
    radmin = _login(client, s["radmin"])
    r = client.get("/api/v1/users", headers=radmin)
    assert r.status_code == 200, r.text
    users = r.json()
    by_email = {u["email"]: u for u in users}
    # role_names is present and correct, so the UI can show only interview_panel members.
    assert "role_names" in users[0]
    assert "interview_panel" in by_email[s["panel1_email"]]["role_names"]
    assert "recruiter_admin" in by_email[s["radmin"]]["role_names"]
    # No password material is ever returned.
    assert all("password" not in u and "password_hash" not in u for u in users)


# --------------------------------------------------------------------------------------
# Issue 3: System Admin assigned-users overview (metadata only) + authorisation.
# --------------------------------------------------------------------------------------
def test_system_admin_assignment_overview_lists_assignments(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])
    # Create two assignments (same campaign, two interviewers) to prove multiple per job.
    for pid in (s["panel1_id"], s["panel2_id"]):
        r = client.post(
            f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
            headers=sys, json={"interviewer_id": pid},
        )
        assert r.status_code == 201, r.text

    r = client.get("/api/v1/interviews/assignments", headers=sys)
    assert r.status_code == 200, r.text
    overview = r.json()
    net_rows = [a for a in overview if a["campaign_id"] == str(s["net_id"])]
    assert len(net_rows) >= 2
    sample = net_rows[0]
    # Rich, non-sensitive metadata is present.
    for key in (
        "interviewer_name", "interviewer_email", "interviewer_role_names",
        "campaign_name", "is_active",
    ):
        assert key in sample
    # Crucially: NO candidate content leaks through this admin view.
    blob = r.text.lower()
    assert "resume" not in blob
    assert "criteria_scores" not in blob and "score" not in blob
    assert "answers" not in blob


def test_assignment_overview_requires_interview_assign(client, engine) -> None:
    s = _seed(engine)
    # A recruiter (no interview.assign) is refused the overview.
    rec = _login(client, s["recruiter"])
    r = client.get("/api/v1/interviews/assignments", headers=rec)
    assert r.status_code == 403, r.text
    # A panel member (assessment.submit, not interview.assign) is also refused.
    panel = _login(client, s["panel1_email"])
    r = client.get("/api/v1/interviews/assignments", headers=panel)
    assert r.status_code == 403, r.text


def test_overview_shows_inactive_after_removal(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])
    created = client.post(
        f"/api/v1/interviews/campaigns/{s['net_id']}/assignments",
        headers=sys, json={"interviewer_id": s["panel1_id"]},
    ).json()
    # Remove (soft-deactivate), then confirm the overview still lists it as inactive.
    r = client.delete(f"/api/v1/interviews/assignments/{created['id']}", headers=sys)
    assert r.status_code == 204, r.text
    r = client.get("/api/v1/interviews/assignments", headers=sys)
    assert r.status_code == 200, r.text
    match = [a for a in r.json() if a["id"] == created["id"]]
    assert len(match) == 1
    assert match[0]["is_active"] is False


# --------------------------------------------------------------------------------------
# User management: System Admin creates an interviewer, it appears in /users (active) and
# in the interviewer dropdown source; delete deactivates it and removes it from the picker.
# --------------------------------------------------------------------------------------
def test_create_interviewer_then_delete_flow(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])

    # 1. System Admin creates an interviewer.
    r = client.post(
        "/api/v1/users",
        headers=sys,
        json={
            "email": "new.interviewer@example.com",
            "display_name": "New Interviewer",
            "password": "CorrectHorseBatteryStaple9",
            "role_names": ["interview_panel"],
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["is_active"] is True
    assert "interview_panel" in created["role_names"]
    # No password material is ever returned.
    assert "password" not in created and "password_hash" not in created
    new_id = created["id"]

    # 2. It appears in the active users list (the dropdown's source) as an interviewer.
    r = client.get("/api/v1/users", headers=sys)
    assert r.status_code == 200, r.text
    active = r.json()
    match = [u for u in active if u["id"] == new_id]
    assert len(match) == 1
    assert "interview_panel" in match[0]["role_names"]

    # 3. Delete (soft) the user.
    r = client.delete(f"/api/v1/users/{new_id}", headers=sys)
    assert r.status_code == 204, r.text

    # 4. The default users list (active only) no longer includes them -> not selectable.
    r = client.get("/api/v1/users", headers=sys)
    assert all(u["id"] != new_id for u in r.json())

    # 5. The admin table (include_inactive) still shows them, as Inactive (safe soft-delete).
    r = client.get("/api/v1/users?include_inactive=true", headers=sys)
    inactive_match = [u for u in r.json() if u["id"] == new_id]
    assert len(inactive_match) == 1
    assert inactive_match[0]["is_active"] is False


def test_cannot_delete_own_account(client, engine) -> None:
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])
    me = client.get("/api/v1/auth/me", headers=sys).json()
    r = client.delete(f"/api/v1/users/{me['user_id']}", headers=sys)
    assert r.status_code == 422, r.text  # cannot delete your own account


def test_delete_user_requires_user_manage(client, engine) -> None:
    s = _seed(engine)
    # Recruiter Admin does not hold user.manage -> cannot delete users.
    radmin = _login(client, s["radmin"])
    # Target: panel1 user id.
    r = client.delete(f"/api/v1/users/{s['panel1_id']}", headers=radmin)
    assert r.status_code == 403, r.text


def test_deactivated_interviewer_removed_from_dropdown_source(client, engine) -> None:
    """After deactivation the user must disappear from the active /users list that feeds the
    Recruiter Admin interviewer dropdown."""
    s = _seed(engine)
    sys = _login(client, s["sysadmin"])
    client.delete(f"/api/v1/users/{s['panel1_id']}", headers=sys)

    radmin = _login(client, s["radmin"])
    r = client.get("/api/v1/users", headers=radmin)
    assert r.status_code == 200, r.text
    ids = {u["id"] for u in r.json()}
    assert s["panel1_id"] not in ids  # inactive interviewer no longer selectable
