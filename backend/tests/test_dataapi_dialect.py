"""Aurora Data API fix-ups: UUID round-trip and retry while an auto-paused cluster resumes.

No database or AWS access needed: the dialect's type processors and the client proxy are
exercised directly. SYNTHETIC values only.
"""

from __future__ import annotations

import uuid

import pytest
from botocore.exceptions import ClientError

from app.db import dataapi
from app.db.dataapi import _DataApiUuid, _ResumeRetryingClient


def _resuming() -> ClientError:
    return ClientError(
        {"Error": {"Code": "DatabaseResumingException", "Message": "resuming"}}, "BeginTransaction"
    )


class _FlakyClient:
    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.failures = failures
        self.error = error or _resuming()
        self.calls = 0
        self.region = "ap-south-1"

    def begin_transaction(self, **_: object) -> dict[str, str]:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return {"transactionId": "synthetic-tx"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataapi.time, "sleep", lambda _s: None)


def test_retries_until_database_resumes() -> None:
    client = _FlakyClient(failures=3)
    assert _ResumeRetryingClient(client).begin_transaction() == {"transactionId": "synthetic-tx"}
    assert client.calls == 4


def test_gives_up_after_the_retry_budget() -> None:
    client = _FlakyClient(failures=100)
    with pytest.raises(ClientError):
        _ResumeRetryingClient(client).begin_transaction()
    assert client.calls == len(dataapi._RESUME_DELAYS_SECONDS) + 1


def test_other_errors_are_not_retried() -> None:
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Begin")
    client = _FlakyClient(failures=1, error=denied)
    with pytest.raises(ClientError):
        _ResumeRetryingClient(client).begin_transaction()
    assert client.calls == 1


def test_non_callable_attributes_pass_through() -> None:
    assert _ResumeRetryingClient(_FlakyClient(0)).region == "ap-south-1"


def test_uuid_results_become_uuid_objects() -> None:
    value = "905a2f76-6c68-495d-b938-50f2e84fd956"
    as_uuid = _DataApiUuid(as_uuid=True).result_processor(None, None)
    assert as_uuid(value) == uuid.UUID(value)
    assert as_uuid(None) is None
    as_str = _DataApiUuid(as_uuid=False).result_processor(None, None)
    assert as_str(value) == value


def test_uuid_binds_as_text() -> None:
    value = uuid.UUID("905a2f76-6c68-495d-b938-50f2e84fd956")
    bind = _DataApiUuid(as_uuid=True).bind_processor(None)
    assert bind(value) == str(value)
    assert bind(None) is None
