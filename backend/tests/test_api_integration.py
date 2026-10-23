"""API integration tests: health, login flow, RBAC enforcement, error envelope."""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.modules.identity.permissions import RoleName
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"


def _seed(engine, role_name: RoleName = RoleName.SYSTEM_ADMIN):  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        org = make_org(session)
        role = make_role(session, org, role_name)
        user = make_user(session, org, roles=[role], password=PASSWORD)
        session.commit()
        return org.id, user.email
    finally:
        session.close()


def test_health_and_ready(client) -> None:
    assert client.get("/health").status_code == 200
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] in {"ready", "degraded"}


def test_login_me_flow(client, engine) -> None:
    _, email = _seed(engine)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_login_bad_password_uses_error_envelope(client, engine) -> None:
    _, email = _seed(engine)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "authentication_error"
    assert "correlation_id" in body["error"]


def test_me_requires_bearer(client) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_rbac_create_user_requires_user_manage(client, engine) -> None:
    # Recruiter Admin lacks user.manage -> 403.
    _, email = _seed(engine, RoleName.RECRUITER_ADMIN)
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()
    resp = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={
            "email": "new.synthetic@example.com",
            "display_name": "SYNTHETIC New",
            "password": "AnotherStrongPassword12",
            "role_names": [],
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "permission_denied"


def test_system_admin_can_create_user(client, engine) -> None:
    _, email = _seed(engine, RoleName.SYSTEM_ADMIN)
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()
    resp = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={
            "email": "new.synthetic@example.com",
            "display_name": "SYNTHETIC New",
            "password": "AnotherStrongPassword12",
            "role_names": [],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "new.synthetic@example.com"


def test_correlation_id_and_security_headers_present(client) -> None:
    resp = client.get("/health")
    assert resp.headers.get("X-Correlation-ID")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Content-Security-Policy") == "default-src 'self'"
