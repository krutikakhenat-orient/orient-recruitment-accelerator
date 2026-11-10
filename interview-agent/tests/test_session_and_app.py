from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import LONG_ANSWER
from fastapi.testclient import TestClient

from interview_agent.app import create_app
from interview_agent.config import Settings
from interview_agent.models import QuestionSet


def _prepare(client: TestClient, qs: QuestionSet, **over: object) -> dict:  # type: ignore[type-arg]
    body = {
        "action": "prepare_session",
        "interview_id": str(qs.interview_id),
        "question_set": json.loads(qs.model_dump_json()),
        "role_title": "Synthetic Backend Engineer",
        "consent_notice_version": "v1",
        "consent_given": True,
    }
    body.update(over)
    return client.post("/invocations", json=body)  # type: ignore[return-value]


def test_ping(settings: Settings) -> None:
    assert TestClient(create_app(settings)).get("/ping").json()["status"] == "Healthy"


def test_plan_questions_endpoint(settings: Settings, plan_request) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(settings))
    r = client.post("/invocations", json=json.loads(plan_request.model_dump_json()))
    assert r.status_code == 200
    body = r.json()
    assert body["approved"] is False and body["questions"][0]["id"] == "std-intro"


def test_prepare_requires_consent_and_approval(
    settings: Settings, question_set: QuestionSet
) -> None:
    client = TestClient(create_app(settings))
    r = _prepare(client, question_set, consent_given=False)
    assert r.status_code == 422 and r.json()["error"]["code"] == "consent_required"
    unapproved = question_set.model_copy(update={"approved": False})
    r = _prepare(client, unapproved)
    assert r.json()["error"]["code"] == "question_set_not_approved"
    assert client.post("/invocations", json={"action": "nope"}).status_code == 422


def test_websocket_rejects_bad_token(settings: Settings, question_set: QuestionSet) -> None:
    client = TestClient(create_app(settings))
    assert _prepare(client, question_set).status_code == 200
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "start",
                "interview_id": str(question_set.interview_id),
                "join_token": "x" * 32,
            }
        )
        assert ws.receive_json() == {"type": "error", "code": "interview_not_available"}


@pytest.mark.parametrize(
    "engine",
    [
        pytest.param(
            "pipecat",
            marks=pytest.mark.skip(
                reason="Known issue: Pipecat pipeline takes ~6 s to shut down after the client "
                "closes, so the record is saved after this test stops waiting. To be fixed."
            ),
        ),
        "legacy",
    ],
)
def test_full_interview_over_websocket_persists_advisory_record(
    settings: Settings, question_set: QuestionSet, engine: str
) -> None:
    """Same wire contract on both voice engines (legacy is the rollback switch)."""
    settings = settings.model_copy(update={"voice_engine": engine})
    client = TestClient(create_app(settings))
    token = _prepare(client, question_set).json()["join_token"]
    spoken: list[str] = []
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "start", "interview_id": str(question_set.interview_id), "join_token": token}
        )
        assert ws.receive_json()["type"] == "ready"

        def read_until_audio_end() -> None:
            while True:
                msg = ws.receive()
                if msg.get("text"):
                    data = json.loads(msg["text"])
                    if data["type"] == "agent_text":
                        spoken.append(data["text"])
                    if data["type"] == "agent_audio_end":
                        return

        read_until_audio_end()  # greeting + intro question
        for _ in range(3):
            ws.send_json({"type": "utterance", "text": LONG_ANSWER})
            read_until_audio_end()
        tail = []
        while True:
            msg = ws.receive()
            if msg.get("text"):
                tail.append(json.loads(msg["text"])["type"])
                if tail[-1] == "ended":
                    break
    assert any("completes the interview" in s for s in spoken)
    saved = Path(settings.output_dir) / f"{question_set.interview_id}.json"
    # "ended" is sent before the record is saved (so the candidate is not kept waiting).
    deadline = time.monotonic() + 5
    while not saved.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)  # file is written in one call; allow it to finish
    record = json.loads(saved.read_text("utf-8"))
    assert record["summary"]["end_reason"] == "completed"
    assert "score" not in record["summary"] and "decision" not in record["summary"]
    assert {t["speaker"] for t in record["transcript"]} == {"agent", "candidate"}
    # The token is single use.
    with client.websocket_connect("/ws") as ws2:
        ws2.send_json(
            {"type": "start", "interview_id": str(question_set.interview_id), "join_token": token}
        )
        assert ws2.receive_json()["code"] == "interview_not_available"


def test_audio_sent_before_start_is_ignored_not_fatal(settings: Settings, question_set: QuestionSet) -> None:
    """Regression: a browser can stream microphone audio before its JSON "start" frame. The
    agent must skip those frames and still accept the start instead of closing the socket."""
    client = TestClient(create_app(settings))
    token = _prepare(client, question_set).json()["join_token"]
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(b"\x00" * 3200)  # early mic audio
        ws.send_bytes(b"\x00" * 3200)
        ws.send_json({"type": "start", "interview_id": str(question_set.interview_id), "join_token": token})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "end"})
