"""AI voice-interview integration tests. All data is SYNTHETIC; the agent is a fake."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.deps import settings_dep
from app.core.config import Settings
from app.modules.ai_interviews import service as ai_service
from app.modules.ai_interviews.agent_client import FakeInterviewAgentClient
from app.modules.ai_interviews.models import AiInterviewSession, AiInterviewStatus
from app.modules.ai_interviews.router import get_agent_client
from app.modules.applications.models import Application
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from app.modules.job_descriptions.models import JDVersion, JobDescription
from tests.factories import make_org, make_role, make_user
from tests.test_check_in_out_api import PASSWORD, _apply, _login, _seed

SECRET = "synthetic-webhook-secret-0123456789abcdef"


class RecordingAgent(FakeInterviewAgentClient):
    """Fake agent that remembers what the platform sent it."""

    def __init__(self) -> None:
        super().__init__()
        self.resume_seen: str | None = None
        self.candidate_ref_seen: str | None = None

    def plan_questions(self, **kwargs: Any) -> dict[str, Any]:
        self.resume_seen = kwargs["resume_text"]
        self.candidate_ref_seen = kwargs["candidate_ref"]
        return super().plan_questions(**kwargs)


def _enabled_settings(**overrides: Any) -> Settings:
    return Settings(
        environment="test",  # type: ignore[arg-type]
        jwt_secret="test-secret-value-at-least-32-chars-long!!",
        ai_interview_enabled=True,
        ai_interview_agent_mode="fake",
        ai_interview_webhook_secret=SECRET,
        app_base_url="http://app.test",
        **overrides,
    )


@pytest.fixture
def agent() -> RecordingAgent:
    return RecordingAgent()


@pytest.fixture
def world(engine, client, agent):  # type: ignore[no-untyped-def]
    """Seeded org + admin + campaign (with an approved JD) + one submitted application, and
    the app wired to an ENABLED feature flag and the recording fake agent."""
    data = _seed(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        jd = JobDescription(organisation_id=data["org_id"], campaign_id=data["campaign_id"])
        session.add(jd)
        session.flush()
        session.add(
            JDVersion(
                job_description_id=jd.id,
                organisation_id=data["org_id"],
                version_number=1,
                status="approved",
                position_title="Synthetic Engineer",
                mandatory_skills=["Python"],
                responsibilities=["Build services"],
            )
        )
        session.commit()
    finally:
        session.close()

    settings = _enabled_settings()
    client.app.dependency_overrides[settings_dep] = lambda: settings
    client.app.dependency_overrides[get_agent_client] = lambda: agent
    application_id = _apply(client, data["campaign_id"])
    return {**data, "application_id": application_id, "settings": settings}


def _sign(body: bytes, *, secret: str = SECRET, ts: int | None = None) -> dict[str, str]:
    stamp = str(ts if ts is not None else int(time.time()))
    sig = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Interview-Timestamp": stamp, "X-Interview-Signature": sig}


def _record(interview_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "1",
            "summary": {
                "interview_id": interview_id,
                "end_reason": "completed",
                "overview": "SYNTHETIC overview.",
                "duration_seconds": 120,
                "assessments": [],
                "advisory_notice": "Advisory only.",
            },
            "transcript": [
                {"speaker": "agent", "text": "Hello."},
                {"speaker": "candidate", "text": "Hi, SYNTHETIC answer."},
            ],
        }
    ).encode()


def _to_approved(client, world):  # type: ignore[no-untyped-def]
    headers = _login(client, world["admin_email"])
    created = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                          headers=headers)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    planned = client.post(f"/api/v1/ai-interviews/sessions/{sid}/plan", headers=headers)
    assert planned.status_code == 200, planned.text
    approved = client.post(f"/api/v1/ai-interviews/sessions/{sid}/approve", json={},
                           headers=headers)
    assert approved.status_code == 200, approved.text
    token = approved.json()["link_url"].rsplit("/", 1)[1]
    return headers, sid, token, approved.json()


# --------------------------------------------------------------------------- full flow


def test_full_flow_plan_approve_consent_run_result(client, world, agent) -> None:  # type: ignore[no-untyped-def]
    headers, sid, token, approved = _to_approved(client, world)

    assert approved["link_url"].startswith("http://app.test/ai-interview/")
    assert approved["session"]["status"] == "approved"
    assert approved["session"]["generated_by"] == "deterministic_fallback"
    assert len(approved["session"]["questions"]) == 2

    # Candidate: preview, then start with consent.
    preview = client.post("/api/v1/ai-interviews/public/preview", json={"token": token})
    assert preview.status_code == 200
    assert preview.json()["role_title"] == "Synthetic Engineer"
    notice_version = preview.json()["notice_version"]

    started = client.post(
        "/api/v1/ai-interviews/public/start",
        json={"token": token, "consent": True, "notice_version": notice_version},
    )
    assert started.status_code == 200, started.text
    assert started.json()["join_token"] == "fake-join-token-0123456789"
    assert started.json()["interview_id"] == sid
    # prepare_session and the socket share one runtime session id (>= 33 chars).
    assert agent.prepared[0]["runtime_session_id"] == f"ora-ai-interview-{sid}"
    assert len(agent.prepared[0]["runtime_session_id"]) >= 33

    # Agent posts the signed result; a retry is idempotent.
    body = _record(sid)
    first = client.post("/api/v1/ai-interviews/webhook", content=body, headers=_sign(body))
    assert first.status_code == 202, first.text
    again = client.post("/api/v1/ai-interviews/webhook", content=body, headers=_sign(body))
    assert again.status_code == 202

    # The link is dead after completion.
    dead = client.post("/api/v1/ai-interviews/public/preview", json={"token": token})
    assert dead.status_code == 404

    # Staff see the advisory summary but never a score/verdict field.
    listing = client.get(
        f"/api/v1/ai-interviews/campaigns/{world['campaign_id']}/sessions", headers=headers
    ).json()
    assert listing[0]["status"] == "completed"
    assert listing[0]["summary"]["overview"] == "SYNTHETIC overview."
    assert "transcript" not in listing[0]
    assert not {"score", "rank", "verdict", "decision"} & set(listing[0])

    transcript = client.get(f"/api/v1/ai-interviews/sessions/{sid}/transcript", headers=headers)
    assert transcript.status_code == 200
    assert [t["speaker"] for t in transcript.json()["turns"]] == ["agent", "candidate"]


def test_agent_only_receives_redacted_resume_and_opaque_ref(client, world, agent) -> None:  # type: ignore[no-untyped-def]
    _to_approved(client, world)
    assert agent.resume_seen is not None
    assert "cand@example.com" not in agent.resume_seen
    assert agent.candidate_ref_seen == world["application_id"]


def test_ai_interview_never_changes_application_state(client, world, engine) -> None:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    def state() -> str:
        s = factory()
        try:
            return s.get(Application, uuid.UUID(world["application_id"])).state  # type: ignore[union-attr]
        finally:
            s.close()

    before = state()
    _, sid, token, _ = _to_approved(client, world)
    client.post(
        "/api/v1/ai-interviews/public/start",
        json={"token": token, "consent": True, "notice_version": ai_service.NOTICE_VERSION},
    )
    body = _record(sid)
    client.post("/api/v1/ai-interviews/webhook", content=body, headers=_sign(body))
    assert state() == before


# --------------------------------------------------------------------------- consent + links


def test_start_requires_consent_and_current_notice(client, world) -> None:  # type: ignore[no-untyped-def]
    _, _, token, _ = _to_approved(client, world)
    no_consent = client.post(
        "/api/v1/ai-interviews/public/start",
        json={"token": token, "consent": False, "notice_version": ai_service.NOTICE_VERSION},
    )
    assert no_consent.status_code == 422
    stale = client.post(
        "/api/v1/ai-interviews/public/start",
        json={"token": token, "consent": True, "notice_version": "old-notice"},
    )
    assert stale.status_code == 422


def test_unknown_token_is_a_generic_404(client, world) -> None:  # type: ignore[no-untyped-def]
    resp = client.post(
        "/api/v1/ai-interviews/public/preview", json={"token": "x" * 43}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["message"] == "This interview link is not valid."


def test_raw_token_is_never_stored(client, world, engine) -> None:  # type: ignore[no-untyped-def]
    _, sid, token, _ = _to_approved(client, world)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        row = s.get(AiInterviewSession, uuid.UUID(sid))
        assert row is not None
        assert row.link_token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps(row.question_set)
    finally:
        s.close()


def test_start_is_limited_and_reissue_replaces_the_link(client, world) -> None:  # type: ignore[no-untyped-def]
    headers, sid, token, _ = _to_approved(client, world)
    payload = {"token": token, "consent": True, "notice_version": ai_service.NOTICE_VERSION}
    for _ in range(3):
        assert client.post("/api/v1/ai-interviews/public/start", json=payload).status_code == 200
    assert client.post("/api/v1/ai-interviews/public/start", json=payload).status_code == 409

    fresh = client.post(f"/api/v1/ai-interviews/sessions/{sid}/link", headers=headers)
    assert fresh.status_code == 200
    new_token = fresh.json()["link_url"].rsplit("/", 1)[1]
    assert new_token != token
    assert client.post("/api/v1/ai-interviews/public/preview",
                       json={"token": token}).status_code == 404
    assert client.post("/api/v1/ai-interviews/public/preview",
                       json={"token": new_token}).status_code == 200


def test_expired_link_is_rejected(client, world, engine) -> None:  # type: ignore[no-untyped-def]
    import datetime as dt

    _, sid, token, _ = _to_approved(client, world)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        row = s.get(AiInterviewSession, uuid.UUID(sid))
        row.link_expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)  # type: ignore[union-attr]
        s.commit()
    finally:
        s.close()
    assert client.post("/api/v1/ai-interviews/public/preview",
                       json={"token": token}).status_code == 409


def test_revoke_kills_the_link(client, world) -> None:  # type: ignore[no-untyped-def]
    headers, sid, token, _ = _to_approved(client, world)
    assert client.post(f"/api/v1/ai-interviews/sessions/{sid}/revoke",
                       headers=headers).status_code == 200
    assert client.post("/api/v1/ai-interviews/public/preview",
                       json={"token": token}).status_code == 404


# --------------------------------------------------------------------------- approval rules


def test_questions_can_be_edited_and_trimmed_on_approval(client, world) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, world["admin_email"])
    sid = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                      headers=headers).json()["id"]
    client.post(f"/api/v1/ai-interviews/sessions/{sid}/plan", headers=headers)
    resp = client.post(
        f"/api/v1/ai-interviews/sessions/{sid}/approve",
        json={"questions": [{"id": "q1", "text": "Walk me through a Python service you built."}]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    questions = resp.json()["session"]["questions"]
    assert [q["id"] for q in questions] == ["q1"]
    assert questions[0]["text"] == "Walk me through a Python service you built."


def test_cannot_approve_before_questions_are_planned(client, world) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, world["admin_email"])
    sid = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                      headers=headers).json()["id"]
    resp = client.post(f"/api/v1/ai-interviews/sessions/{sid}/approve", json={},
                       headers=headers)
    assert resp.status_code == 409


def test_unknown_question_id_is_rejected(client, world) -> None:  # type: ignore[no-untyped-def]
    headers = _login(client, world["admin_email"])
    sid = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                      headers=headers).json()["id"]
    client.post(f"/api/v1/ai-interviews/sessions/{sid}/plan", headers=headers)
    resp = client.post(
        f"/api/v1/ai-interviews/sessions/{sid}/approve",
        json={"questions": [{"id": "nope", "text": "A made up question here."}]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_recruiter_without_approve_permission_cannot_approve(client, world, engine) -> None:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        from app.modules.identity.models import Organisation

        org = s.get(Organisation, world["org_id"])
        role = make_role(s, org, RoleName.RECRUITER)  # type: ignore[arg-type]
        user = make_user(s, org, roles=[role], password=PASSWORD,  # type: ignore[arg-type]
                         email="recruiter@example.com")
        s.add(CampaignAssignment(user_id=user.id, campaign_id=world["campaign_id"],
                                 organisation_id=world["org_id"]))
        s.commit()
    finally:
        s.close()

    admin = _login(client, world["admin_email"])
    sid = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                      headers=admin).json()["id"]
    client.post(f"/api/v1/ai-interviews/sessions/{sid}/plan", headers=admin)

    recruiter = _login(client, "recruiter@example.com")
    assert client.post(f"/api/v1/ai-interviews/sessions/{sid}/approve", json={},
                       headers=recruiter).status_code == 403
    # ...and the recruiter has no candidate.view_pii, so no transcript either.
    assert client.get(f"/api/v1/ai-interviews/sessions/{sid}/transcript",
                      headers=recruiter).status_code == 403


def test_other_organisation_cannot_see_the_session(client, world, engine) -> None:  # type: ignore[no-untyped-def]
    admin = _login(client, world["admin_email"])
    sid = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                      headers=admin).json()["id"]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        from app.modules.identity.service import _issue_tokens

        other_org = make_org(s, "SYNTHETIC Other Org")
        role = make_role(s, other_org, RoleName.RECRUITER_ADMIN)
        other_user = make_user(
            s, other_org, roles=[role], password=PASSWORD, email="other@example.com"
        )
        s.commit()
        # Login is single-organisation (multi-tenant is out of scope), so mint a token for
        # the second organisation's user directly.
        tokens = _issue_tokens(world["settings"], other_user)
    finally:
        s.close()
    other = {"Authorization": f"Bearer {tokens.access_token}"}
    assert client.get(f"/api/v1/ai-interviews/sessions/{sid}/transcript",
                      headers=other).status_code == 404
    assert client.post(f"/api/v1/ai-interviews/sessions/{sid}/revoke",
                       headers=other).status_code == 404


# --------------------------------------------------------------------------- webhook security


def test_webhook_rejects_bad_signature_stale_timestamp_and_no_headers(client, world) -> None:  # type: ignore[no-untyped-def]
    _, sid, _, _ = _to_approved(client, world)
    body = _record(sid)
    url = "/api/v1/ai-interviews/webhook"
    assert client.post(url, content=body).status_code == 401
    assert client.post(url, content=body,
                       headers=_sign(body, secret="wrong-" + SECRET)).status_code == 401
    stale = _sign(body, ts=int(time.time()) - 3600)
    assert client.post(url, content=body, headers=stale).status_code == 401
    tampered = _sign(body)
    assert client.post(url, content=body + b" ", headers=tampered).status_code == 401


def test_webhook_rejects_malformed_record_and_unknown_interview(client, world) -> None:  # type: ignore[no-untyped-def]
    url = "/api/v1/ai-interviews/webhook"
    junk = json.dumps({"schema_version": "1", "summary": {}, "transcript": []}).encode()
    assert client.post(url, content=junk, headers=_sign(junk)).status_code == 422
    unknown = _record(str(uuid.uuid4()))
    assert client.post(url, content=unknown, headers=_sign(unknown)).status_code == 404


# --------------------------------------------------------------------------- feature flag + hook


def test_feature_is_off_by_default(client, world) -> None:  # type: ignore[no-untyped-def]
    client.app.dependency_overrides[settings_dep] = lambda: Settings(
        environment="test",  # type: ignore[arg-type]
        jwt_secret="test-secret-value-at-least-32-chars-long!!",
    )
    headers = _login(client, world["admin_email"])
    resp = client.post(f"/api/v1/ai-interviews/applications/{world['application_id']}",
                       headers=headers)
    assert resp.status_code == 409


def test_screening_hook_drafts_only_when_enabled_and_is_idempotent(world, engine) -> None:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        application = s.get(Application, uuid.UUID(world["application_id"]))
        off = Settings(environment="test",  # type: ignore[arg-type]
                       jwt_secret="test-secret-value-at-least-32-chars-long!!")
        assert ai_service.draft_after_screening(s, settings=off, application=application) is None  # type: ignore[arg-type]

        first = ai_service.draft_after_screening(
            s, settings=world["settings"], application=application  # type: ignore[arg-type]
        )
        second = ai_service.draft_after_screening(
            s, settings=world["settings"], application=application  # type: ignore[arg-type]
        )
        assert first is not None and second is not None and first.id == second.id
        assert first.status == AiInterviewStatus.PENDING_PLAN.value
        assert first.link_token_hash is None  # a draft has no candidate link
    finally:
        s.close()


def _progress(engine, world, monkeypatch, *, settings, conflict=False):  # type: ignore[no-untyped-def]
    """Drive the real screening progression step on a SCREENED application."""
    from types import SimpleNamespace

    from app.core import config as config_module
    from app.modules.applications.states import ApplicationState
    from app.modules.screening import service as screening_service

    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        application = s.get(Application, uuid.UUID(world["application_id"]))
        application.state = ApplicationState.SCREENED.value  # type: ignore[union-attr]
        s.flush()
        run = SimpleNamespace(score=80.0, conflict_flagged=conflict, recommendation="eligible")
        progressed = screening_service.auto_progress_to_interview(
            s, organisation_id=application.organisation_id,  # type: ignore[union-attr]
            application=application, run=run,  # type: ignore[arg-type]
        )
        s.commit()
        rows = ai_service.list_sessions(
            s, organisation_id=world["org_id"], campaign_id=world["campaign_id"]
        )
        return progressed, rows
    finally:
        s.close()


def test_screening_progression_drafts_an_ai_interview(engine, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    progressed, rows = _progress(engine, world, monkeypatch, settings=world["settings"])
    assert progressed is True
    assert [r.status for r in rows] == [AiInterviewStatus.PENDING_PLAN.value]
    # A draft only: no questions, no link, nothing sent to the candidate or the agent.
    assert rows[0].question_set is None and rows[0].link_token_hash is None


def test_no_ai_draft_when_screening_flags_a_conflict(engine, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    progressed, rows = _progress(
        engine, world, monkeypatch, settings=world["settings"], conflict=True
    )
    assert progressed is False
    assert rows == []


def test_no_ai_draft_when_feature_is_off_but_progression_still_works(  # type: ignore[no-untyped-def]
    engine, world, monkeypatch
) -> None:
    off = Settings(environment="test",  # type: ignore[arg-type]
                   jwt_secret="test-secret-value-at-least-32-chars-long!!")
    progressed, rows = _progress(engine, world, monkeypatch, settings=off)
    assert progressed is True
    assert rows == []


# --------------------------------------------------------------------------- unit


def test_redaction_strips_contact_details() -> None:
    text = "Reach me at jane.doe@example.com or +91 98765 43210 or https://x.example/in/jane"
    out = ai_service.redact_resume_text(text)
    assert "jane.doe@example.com" not in out
    assert "98765" not in out
    assert "https://x.example" not in out


def test_agentcore_connection_url_is_presigned_without_extra_dependency(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The browser gets a SigV4 query-signed wss:// URL for one runtime session, signed locally."""
    from urllib.parse import parse_qs, urlparse

    from app.core.config import Settings
    from app.modules.ai_interviews.agent_client import AgentCoreInterviewAgentClient

    # Synthetic, non-functional credentials: signing is local and makes no AWS call.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIASYNTHETICTEST000")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret-not-real")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    arn = "arn:aws:bedrock-agentcore:ap-south-1:000000000000:runtime/synthetic-agent"
    client = AgentCoreInterviewAgentClient(
        Settings(ai_interview_agentcore_arn=arn, ai_interview_agentcore_region="ap-south-1")
    )
    url = urlparse(client.connection_url(runtime_session_id="s" * 40))
    params = parse_qs(url.query)
    assert url.scheme == "wss"
    assert url.netloc == "bedrock-agentcore.ap-south-1.amazonaws.com"
    assert url.path.endswith("/ws")
    assert params["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == ["s" * 40]
    assert params["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert params["X-Amz-Expires"] == ["60"]
    assert "X-Amz-Signature" in params


# --------------------------------------------------------------------------- retry


def _finish(client, sid: str, token: str, end_reason: str = "candidate_requested_stop") -> None:  # type: ignore[no-untyped-def]
    started = client.post(
        "/api/v1/ai-interviews/public/start",
        json={"token": token, "consent": True, "notice_version": ai_service.NOTICE_VERSION},
    )
    assert started.status_code == 200, started.text
    record = json.loads(_record(sid))
    record["summary"]["end_reason"] = end_reason
    body = json.dumps(record).encode()
    done = client.post("/api/v1/ai-interviews/webhook", content=body, headers=_sign(body))
    assert done.status_code == 202, done.text


def test_retry_creates_a_new_attempt_and_keeps_the_first(client, world) -> None:  # type: ignore[no-untyped-def]
    headers, sid, token, approved = _to_approved(client, world)
    _finish(client, sid, token)

    resp = client.post(f"/api/v1/ai-interviews/sessions/{sid}/retry",
                       json={"reason": "Call dropped; SYNTHETIC candidate asked to try again"},
                       headers=headers)
    assert resp.status_code == 201, resp.text
    new = resp.json()
    assert new["session"]["id"] != sid
    assert new["session"]["status"] == "approved"
    assert [q["text"] for q in new["session"]["questions"]] == [
        q["text"] for q in approved["session"]["questions"]
    ]
    # The fresh link works; the first attempt's result is untouched.
    new_token = new["link_url"].rsplit("/", 1)[1]
    assert client.post("/api/v1/ai-interviews/public/preview",
                       json={"token": new_token}).status_code == 200
    rows = {r["id"]: r for r in client.get(
        f"/api/v1/ai-interviews/campaigns/{world['campaign_id']}/sessions", headers=headers
    ).json()}
    assert rows[sid]["status"] == "completed"
    assert rows[sid]["end_reason"] == "candidate_requested_stop"
    assert rows[sid]["summary"]["overview"] == "SYNTHETIC overview."
    assert len(rows) == 2

    # The new attempt can run to completion on its own record.
    _finish(client, new["session"]["id"], new_token, end_reason="completed")


def test_retry_rules(client, world) -> None:  # type: ignore[no-untyped-def]
    headers, sid, token, _ = _to_approved(client, world)
    url = f"/api/v1/ai-interviews/sessions/{sid}/retry"
    # Not finished yet -> nothing to retry.
    assert client.post(url, json={"reason": "SYNTHETIC reason"}, headers=headers).status_code == 409
    _finish(client, sid, token)
    # A reason is required.
    assert client.post(url, json={"reason": "  "}, headers=headers).status_code == 422
    assert client.post(url, json={"reason": "SYNTHETIC retry"}, headers=headers).status_code == 201
    # Only one open attempt at a time.
    assert client.post(url, json={"reason": "SYNTHETIC again"}, headers=headers).status_code == 409


def test_retry_is_capped_per_application(client, world) -> None:  # type: ignore[no-untyped-def]
    capped = _enabled_settings(ai_interview_max_attempts=2)
    client.app.dependency_overrides[settings_dep] = lambda: capped
    headers, sid, token, _ = _to_approved(client, world)
    _finish(client, sid, token)
    second = client.post(f"/api/v1/ai-interviews/sessions/{sid}/retry",
                         json={"reason": "SYNTHETIC retry 1"}, headers=headers).json()
    second_id = second["session"]["id"]
    _finish(client, second_id, second["link_url"].rsplit("/", 1)[1], end_reason="no_response")
    third = client.post(f"/api/v1/ai-interviews/sessions/{second_id}/retry",
                        json={"reason": "SYNTHETIC retry 2"}, headers=headers)
    assert third.status_code == 409
    assert "attempts" in third.json()["error"]["message"]


def test_retry_requires_interview_approve(client, world, engine) -> None:  # type: ignore[no-untyped-def]
    headers, sid, token, _ = _to_approved(client, world)
    _finish(client, sid, token)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        from app.modules.identity.models import Organisation

        org = s.get(Organisation, world["org_id"])
        role = make_role(s, org, RoleName.RECRUITER)  # type: ignore[arg-type]
        user = make_user(s, org, roles=[role], password=PASSWORD,  # type: ignore[arg-type]
                         email="retry.recruiter@example.com")
        s.add(CampaignAssignment(user_id=user.id, campaign_id=world["campaign_id"],
                                 organisation_id=world["org_id"]))
        s.commit()
    finally:
        s.close()
    recruiter = _login(client, "retry.recruiter@example.com")
    assert client.post(f"/api/v1/ai-interviews/sessions/{sid}/retry",
                       json={"reason": "SYNTHETIC reason"}, headers=recruiter).status_code == 403


def test_retry_binds_questions_to_the_new_attempt(client, world, agent, engine) -> None:  # type: ignore[no-untyped-def]
    """The agent rejects a question set bound to another interview (422 interview_mismatch).
    A retry must re-bind it, and attempts created before that fix are repaired on start."""
    headers, sid, token, _ = _to_approved(client, world)
    _finish(client, sid, token)
    new = client.post(f"/api/v1/ai-interviews/sessions/{sid}/retry",
                      json={"reason": "SYNTHETIC retry"}, headers=headers).json()
    new_id = new["session"]["id"]

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        row = s.get(AiInterviewSession, uuid.UUID(new_id))
        assert row is not None and row.question_set is not None
        assert row.question_set["interview_id"] == new_id
        # Simulate a pre-fix attempt still carrying the first attempt's id.
        row.question_set = {**row.question_set, "interview_id": sid}
        s.commit()
    finally:
        s.close()

    started = client.post(
        "/api/v1/ai-interviews/public/start",
        json={"token": new["link_url"].rsplit("/", 1)[1], "consent": True,
              "notice_version": ai_service.NOTICE_VERSION},
    )
    assert started.status_code == 200, started.text
    assert agent.prepared[-1]["interview_id"] == new_id
