"""Browser session restore: the refresh token travels in an HttpOnly cookie so a hard refresh
can obtain a new in-memory access token without the user logging in again. SYNTHETIC data."""

from __future__ import annotations

from tests.test_api_integration import PASSWORD, _seed

CSRF = {"X-Requested-With": "ora-web"}


def _login(client, engine):  # type: ignore[no-untyped-def]
    _, email = _seed(engine)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp


def test_login_sets_a_locked_down_refresh_cookie(client, engine) -> None:  # type: ignore[no-untyped-def]
    resp = _login(client, engine)
    cookie = resp.headers["set-cookie"].lower()
    assert "ora_refresh=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie


def test_refresh_from_cookie_restores_a_working_access_token(client, engine) -> None:  # type: ignore[no-untyped-def]
    _login(client, engine)
    # No body, no Authorization header: only the cookie jar, exactly like a page reload.
    refreshed = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert refreshed.status_code == 200, refreshed.text
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert me.status_code == 200


def test_cookie_refresh_is_rotated(client, engine) -> None:  # type: ignore[no-untyped-def]
    _login(client, engine)
    refreshed = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert "ora_refresh=" in refreshed.headers["set-cookie"]


def test_cookie_refresh_requires_the_csrf_header(client, engine) -> None:  # type: ignore[no-untyped-def]
    _login(client, engine)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_any_credentials_is_rejected(client) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_refresh_with_a_forged_cookie_is_rejected_and_cleared(client) -> None:  # type: ignore[no-untyped-def]
    client.cookies.set("ora_refresh", "not-a-real-token", path="/api/v1/auth")
    resp = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert resp.status_code == 401
    assert 'ora_refresh=""' in resp.headers["set-cookie"] or "max-age=0" in (
        resp.headers["set-cookie"].lower()
    )


def test_body_based_refresh_still_works_for_api_clients(client, engine) -> None:  # type: ignore[no-untyped-def]
    tokens = _login(client, engine).json()
    client.cookies.clear()
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_logout_clears_the_cookie_so_refresh_stops_working(client, engine) -> None:  # type: ignore[no-untyped-def]
    _login(client, engine)
    out = client.post("/api/v1/auth/logout")
    assert out.status_code == 204
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_an_access_token_cannot_be_used_as_a_refresh_cookie(client, engine) -> None:  # type: ignore[no-untyped-def]
    tokens = _login(client, engine).json()
    client.cookies.clear()
    client.cookies.set("ora_refresh", tokens["access_token"], path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401
