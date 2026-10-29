"""Induction feature tests: employee self-service flow + RBAC gating.

Covers: status reporting, certificate gating before completion, idempotent completion,
HTML certificate after completion, and that a staff role (RECRUITER_ADMIN) is denied the
induction endpoints because it lacks induction.view.
"""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.modules.identity.permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    Permission,
    RoleName,
)
from app.modules.induction.models import InductionCompletion
from app.modules.induction.service import seed_developer_video
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"


def _session(engine):  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    return factory()


def _seed_user(engine, role_name: RoleName, *, email: str, with_video: bool = True):  # type: ignore[no-untyped-def]
    session = _session(engine)
    try:
        org = make_org(session)
        role = make_role(session, org, role_name)
        user = make_user(session, org, email=email, roles=[role], password=PASSWORD)
        if with_video:
            seed_developer_video(session, org.id)
        session.commit()
        return org.id, user.email
    finally:
        session.close()


def _login(client, email: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_employee_status_has_video_not_completed(client, engine) -> None:
    _, email = _seed_user(engine, RoleName.EMPLOYEE, email="synthetic.employee@example.com")
    headers = _login(client, email)
    resp = client.get("/api/v1/induction/me", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_video"] is True
    assert body["completed"] is False
    assert body["completed_at"] is None


def test_certificate_before_completion_is_rejected(client, engine) -> None:
    _, email = _seed_user(engine, RoleName.EMPLOYEE, email="synthetic.employee@example.com")
    headers = _login(client, email)
    resp = client.get("/api/v1/induction/certificate", headers=headers)
    assert 400 <= resp.status_code < 500, resp.text


def test_complete_is_idempotent(client, engine) -> None:
    org_id, email = _seed_user(
        engine, RoleName.EMPLOYEE, email="synthetic.employee@example.com"
    )
    headers = _login(client, email)

    first = client.post("/api/v1/induction/complete", headers=headers)
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/induction/complete", headers=headers)
    assert second.status_code == 200, second.text

    assert first.json()["completed"] is True
    assert first.json()["completed_at"] == second.json()["completed_at"]

    session = _session(engine)
    try:
        completions = (
            session.query(InductionCompletion)
            .filter(InductionCompletion.organisation_id == org_id)
            .all()
        )
        assert len(completions) == 1
    finally:
        session.close()


def test_certificate_after_completion_is_html(client, engine) -> None:
    _, email = _seed_user(engine, RoleName.EMPLOYEE, email="synthetic.employee@example.com")
    headers = _login(client, email)

    assert client.post("/api/v1/induction/complete", headers=headers).status_code == 200

    resp = client.get("/api/v1/induction/certificate", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "synthetic.employee@example.com" in body
    assert "Employee Induction" in body


def test_induction_status_without_video(client, engine) -> None:
    _, email = _seed_user(
        engine,
        RoleName.EMPLOYEE,
        email="synthetic.employee@example.com",
        with_video=False,
    )
    headers = _login(client, email)
    resp = client.get("/api/v1/induction/me", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_video"] is False


def test_staff_role_denied_induction_endpoints(client, engine) -> None:
    # A RECRUITER_ADMIN lacks induction.view -> 403 on gated endpoints.
    _, email = _seed_user(
        engine, RoleName.RECRUITER_ADMIN, email="synthetic.recruiter_admin@example.com"
    )
    headers = _login(client, email)

    complete = client.post("/api/v1/induction/complete", headers=headers)
    assert complete.status_code == 403, complete.text
    assert complete.json()["error"]["code"] == "permission_denied"

    video = client.get("/api/v1/induction/video", headers=headers)
    assert video.status_code == 403, video.text


def test_video_stream_returns_bytes(client, engine) -> None:
    _, email = _seed_user(engine, RoleName.EMPLOYEE, email="synthetic.employee@example.com")
    headers = _login(client, email)
    resp = client.get("/api/v1/induction/video/stream", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("video/mp4")
    assert len(resp.content) > 0


def test_default_role_permissions_only_employee_has_induction_view() -> None:
    for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
        has_it = Permission.INDUCTION_VIEW in perms
        assert has_it == (role is RoleName.EMPLOYEE)


def test_seed_provisions_induction_video(client, engine) -> None:
    # Guards against the in-memory object store leaking across tests: use a fresh org.
    session = _session(engine)
    try:
        org = make_org(session, name="SYNTHETIC Seed Org")
        session.commit()
        org_id = org.id
    finally:
        session.close()

    s2 = _session(engine)
    try:
        v1 = seed_developer_video(s2, org_id)
        s2.commit()
        v2 = seed_developer_video(s2, org_id)
        s2.commit()
        assert v1.id == v2.id  # idempotent
        from app.modules.induction.models import InductionVideo

        count = (
            s2.query(InductionVideo)
            .filter(InductionVideo.organisation_id == org_id)
            .count()
        )
        assert count == 1
    finally:
        s2.close()
