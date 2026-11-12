"""Paused-database handling: the "We are starting up" contract between API and browser.

When Aurora Serverless is resuming from auto-pause, interactive requests must answer quickly with
503 ``service_starting`` (plus Retry-After) instead of hanging, and the public status probe must
never wait. Machine callers (agent webhook, ops jobs) keep the full wait. No AWS access needed:
the Data API's resuming error is simulated. SYNTHETIC data only.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import dataapi
from app.db.dataapi import (
    _ResumeRetryingClient,
    is_database_resuming,
    resume_wait_limit,
)
from app.db.session import get_db
from app.main import create_app, resume_wait_for_path


def _resuming() -> ClientError:
    return ClientError(
        {"Error": {"Code": "DatabaseResumingException", "Message": "resuming"}}, "BeginTransaction"
    )


class _AlwaysResuming:
    def __init__(self) -> None:
        self.calls = 0

    def begin_transaction(self, **_: object) -> dict[str, str]:
        self.calls += 1
        raise _resuming()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataapi.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------- wait budget
def test_zero_limit_fails_on_the_first_resuming_error() -> None:
    client = _AlwaysResuming()
    with resume_wait_limit(0), pytest.raises(ClientError):
        _ResumeRetryingClient(client).begin_transaction()
    assert client.calls == 1  # the single call still wakes the database


def test_short_limit_stops_after_its_budget() -> None:
    client = _AlwaysResuming()
    with resume_wait_limit(6), pytest.raises(ClientError):
        _ResumeRetryingClient(client).begin_transaction()
    assert client.calls == 4  # waits 1 + 2 + 3 = 6 s, then gives up


def test_no_limit_uses_the_full_budget() -> None:
    client = _AlwaysResuming()
    with pytest.raises(ClientError):
        _ResumeRetryingClient(client).begin_transaction()
    assert client.calls == len(dataapi._RESUME_DELAYS_SECONDS) + 1


def test_limit_is_restored_after_the_block() -> None:
    with resume_wait_limit(0):
        pass
    client = _AlwaysResuming()
    with pytest.raises(ClientError):
        _ResumeRetryingClient(client).begin_transaction()
    assert client.calls == len(dataapi._RESUME_DELAYS_SECONDS) + 1


def test_webhook_keeps_the_full_wait_and_pages_wait_briefly() -> None:
    assert resume_wait_for_path("/api/v1/ai-interviews/webhook") is None
    assert resume_wait_for_path("/api/v1/auth/login") == 6.0
    assert resume_wait_for_path("/api/v1/campaigns") == 6.0


# ---------------------------------------------------------------- error detection
def test_detects_resuming_error_wrapped_by_sqlalchemy() -> None:
    wrapped = OperationalError("SELECT 1", {}, _resuming())
    assert is_database_resuming(wrapped) is True


def test_detects_resuming_error_in_exception_chain() -> None:
    try:
        try:
            raise _resuming()
        except ClientError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as outer:
        assert is_database_resuming(outer) is True


def test_other_errors_are_not_resuming() -> None:
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Begin")
    assert is_database_resuming(denied) is False
    assert is_database_resuming(ValueError("x")) is False
    assert is_database_resuming(None) is False


# ---------------------------------------------------------------- HTTP contract
def test_status_reports_ready(client: TestClient) -> None:
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


class _ResumingSession:
    """Stands in for a Session whose every database call hits a resuming Aurora cluster."""

    error: BaseException = _resuming()

    def __getattr__(self, name: str) -> object:
        def fail(*_: object, **__: object) -> None:
            raise OperationalError("SELECT 1", {}, self.error)

        return fail

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _BrokenSession(_ResumingSession):
    error = Exception("connection refused")


def _app_with_session(session: object) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app, raise_server_exceptions=False)


def test_status_reports_starting_while_database_resumes() -> None:
    resp = _app_with_session(_ResumingSession()).get("/api/v1/system/status")
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "3"
    body = resp.json()["error"]
    assert body["code"] == "service_starting"
    assert body["correlation_id"]


def test_status_reports_unavailable_for_other_database_errors() -> None:
    resp = _app_with_session(_BrokenSession()).get("/api/v1/system/status")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"
    assert "Retry-After" not in resp.headers


def test_any_route_answers_service_starting_instead_of_500() -> None:
    # Login reads the user table: with the database resuming it must answer 503, not 500.
    client = _app_with_session(_ResumingSession())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "synthetic.user@example.com", "password": "SyntheticPassword!1"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_starting"
    assert resp.headers["Retry-After"] == "3"
