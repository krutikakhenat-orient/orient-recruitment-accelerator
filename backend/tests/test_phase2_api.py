"""API integration tests for the Phase 2 campaign + JD flow."""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.modules.identity.permissions import RoleName
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"
JD_TEXT = (
    b"Position Title: Synthetic QA Engineer\nDepartment: Quality\n"
    b"Minimum 2 years experience in testing\n"
)


def _seed_hr(engine):  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        org = make_org(session)
        role = make_role(session, org, RoleName.RECRUITER_ADMIN)
        user = make_user(session, org, roles=[role], password=PASSWORD)
        session.commit()
        return user.email
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_project_campaign_jd_flow(client, engine) -> None:
    email = _seed_hr(engine)
    headers = _login(client, email)

    # Create a project.
    pr = client.post("/api/v1/projects", headers=headers,
                     json={"name": "SYNTHETIC Project"})
    assert pr.status_code == 201, pr.text
    project_id = pr.json()["id"]

    # Create a campaign.
    cr = client.post(
        "/api/v1/campaigns", headers=headers,
        json={"project_id": project_id, "name": "SYNTHETIC Campaign",
              "position_title": "Synthetic QA Engineer"},
    )
    assert cr.status_code == 201, cr.text
    campaign = cr.json()
    assert campaign["state"] == "draft"
    campaign_id = campaign["id"]

    # Upload a JD (multipart).
    up = client.post(
        "/api/v1/job-descriptions/upload",
        headers=headers,
        data={"campaign_id": campaign_id},
        files={"file": ("jd.txt", JD_TEXT, "text/plain")},
    )
    assert up.status_code == 201, up.text
    jd_version = up.json()
    assert jd_version["status"] == "draft"
    assert jd_version["position_title"] == "Synthetic QA Engineer"

    # Approve the JD version -> immutable.
    ap = client.post(
        f"/api/v1/job-descriptions/versions/{jd_version['id']}/approve",
        headers=headers, json={"change_reason": "reviewed"},
    )
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"


def test_malicious_upload_rejected_via_api(client, engine) -> None:
    email = _seed_hr(engine)
    headers = _login(client, email)
    project_id = client.post("/api/v1/projects", headers=headers,
                             json={"name": "P"}).json()["id"]
    campaign_id = client.post(
        "/api/v1/campaigns", headers=headers,
        json={"project_id": project_id, "name": "C", "position_title": "T"},
    ).json()["id"]

    # A PNG renamed to .pdf is rejected by signature validation (422).
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    resp = client.post(
        "/api/v1/job-descriptions/upload",
        headers=headers,
        data={"campaign_id": campaign_id},
        files={"file": ("evil.pdf", png, "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_transition_rejects_invalid_destination(client, engine) -> None:
    email = _seed_hr(engine)
    headers = _login(client, email)
    project_id = client.post("/api/v1/projects", headers=headers,
                             json={"name": "P"}).json()["id"]
    campaign_id = client.post(
        "/api/v1/campaigns", headers=headers,
        json={"project_id": project_id, "name": "C", "position_title": "T"},
    ).json()["id"]

    # Draft -> published is not permitted; expect a 409 invalid_transition.
    resp = client.post(
        f"/api/v1/campaigns/{campaign_id}/transition",
        headers=headers, json={"destination": "published", "reason": "skip"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "invalid_transition"


def test_delete_campaign_removes_it_and_audits(client, engine) -> None:
    email = _seed_hr(engine)
    headers = _login(client, email)
    project_id = client.post("/api/v1/projects", headers=headers,
                             json={"name": "P"}).json()["id"]
    campaign_id = client.post(
        "/api/v1/campaigns", headers=headers,
        json={"project_id": project_id, "name": "C", "position_title": "T"},
    ).json()["id"]

    # Delete it: the creator is auto-assigned and holds campaign.edit.
    resp = client.delete(f"/api/v1/campaigns/{campaign_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_campaign_id"] == campaign_id
    assert body["applications_removed"] == 0

    # It is gone.
    assert client.get(f"/api/v1/campaigns/{campaign_id}", headers=headers).status_code == 404


def test_delete_campaign_requires_edit_permission(client, engine) -> None:
    # An interview-panel user (no campaign.edit) cannot delete a campaign.
    from sqlalchemy.orm import sessionmaker

    from tests.factories import make_role, make_user

    admin_email = _seed_hr(engine)
    admin_headers = _login(client, admin_email)
    project_id = client.post("/api/v1/projects", headers=admin_headers,
                             json={"name": "P"}).json()["id"]
    campaign_id = client.post(
        "/api/v1/campaigns", headers=admin_headers,
        json={"project_id": project_id, "name": "C", "position_title": "T"},
    ).json()["id"]

    # A separate panel user in the SAME org.
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        from app.modules.organisations.repository import get_default_organisation

        org = get_default_organisation(session)
        role = make_role(session, org, RoleName.INTERVIEW_PANEL)
        panel = make_user(session, org, roles=[role], email="panel@example.com",
                          password=PASSWORD)
        session.commit()
        panel_email = panel.email
    finally:
        session.close()

    panel_headers = _login(client, panel_email)
    resp = client.delete(f"/api/v1/campaigns/{campaign_id}", headers=panel_headers)
    assert resp.status_code == 403, resp.text
    # Still present for the admin.
    assert client.get(f"/api/v1/campaigns/{campaign_id}", headers=admin_headers).status_code == 200
