"""Approval -> indexing -> answers, with an asynchronous (Bedrock-like) Knowledge Base.

Covers Req 2.1-2.6 and 3.1-3.5: draft content never searchable, sync coalescing, revised
versions stay live until the new one is Ready, failure keeps the previous version, reindex,
retire, and the reconcile job. All content is SYNTHETIC.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.modules.assistant.ratelimit import ask_limiter
from app.modules.assistant.router import get_answer_composer
from app.modules.audit.models import AuditEvent
from app.modules.documents.storage import InMemoryObjectStore
from app.modules.knowledge_base import service as kb_service
from app.modules.knowledge_base.deps import get_knowledge_base, get_policy_file_store
from app.modules.knowledge_base.models import KbSyncRequest
from app.modules.policies.service import source_loader
from tests.chatbot_support import CitingComposer, FakeBedrockKB, login, seed_people


@pytest.fixture
def kb() -> FakeBedrockKB:
    return FakeBedrockKB()


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def hr(client, engine, kb, store):  # type: ignore[no-untyped-def]
    ask_limiter.reset()
    ids = seed_people(engine)
    client.app.dependency_overrides[get_knowledge_base] = lambda: kb
    client.app.dependency_overrides[get_policy_file_store] = lambda: store
    client.app.dependency_overrides[get_answer_composer] = lambda: CitingComposer()
    return {**ids, "admin": login(client, "admin@example.com"),
            "employee": login(client, "employee@example.com"),
            "recruiter": login(client, "recruiter@example.com")}


def _create(client, hr, title, body, **extra):  # type: ignore[no-untyped-def]
    resp = client.post("/api/v1/policies", headers=hr["admin"],
                       json={"title": title, "body": body, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _approve(client, hr, pid):  # type: ignore[no-untyped-def]
    resp = client.post(f"/api/v1/policies/{pid}/approve", headers=hr["admin"])
    assert resp.status_code == 200, resp.text
    return resp.json()


def _status(client, hr, pid):  # type: ignore[no-untyped-def]
    return client.get(f"/api/v1/policies/{pid}/index-status", headers=hr["admin"]).json()


def _ask(client, headers, question):  # type: ignore[no-untyped-def]
    resp = client.post("/api/v1/assistant/ask", headers=headers, json={"question": question})
    assert resp.status_code == 200, resp.text
    return resp.json()


LEAVE = "SYNTHETIC: Employees receive 20 days of paid annual leave each year."


def test_approve_indexes_then_answers_with_citation(client, hr, kb) -> None:  # type: ignore[no-untyped-def]
    pid = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    assert kb.objects == {}  # a draft never reaches approved/ (Req 2.1)
    approved = _approve(client, hr, pid)
    assert approved["index_status"] == "indexing"
    assert all(k.startswith("approved/") for k in kb.objects)

    # Not searchable until the job finishes.
    before = _ask(client, hr["employee"], "How many days of annual leave do I get?")
    assert before["answered_via"] == "bedrock_kb" and before["answered"] is False

    kb.finish(kb.running_job() or "")
    status = _status(client, hr, pid)
    assert status["index_status"] == "ready" and status["ingestion_job_id"] == "JOB1"

    answer = _ask(client, hr["employee"], "How many days of annual leave do I get?")
    assert answer["answered"] is True and answer["answered_via"] == "bedrock_kb"
    assert answer["sources"][0] == {**answer["sources"][0], "ref": 1, "title":
                                    "SYNTHETIC Annual leave", "version": 1, "page": 1}
    assert "[1]" in answer["answer"]


def test_changes_during_a_running_sync_are_coalesced(client, hr, kb) -> None:  # type: ignore[no-untyped-def]
    a = _create(client, hr, "SYNTHETIC Leave", LEAVE)
    b = _create(client, hr, "SYNTHETIC Travel", "SYNTHETIC: Travel is booked through HR.")
    c = _create(client, hr, "SYNTHETIC Dress", "SYNTHETIC: Business casual on weekdays.")
    _approve(client, hr, a)
    _approve(client, hr, b)
    _approve(client, hr, c)
    assert list(kb.jobs) == ["JOB1"]  # b and c joined ONE queued request

    kb.finish("JOB1")
    assert _status(client, hr, a)["index_status"] == "ready"
    assert _status(client, hr, b)["index_status"] == "indexing"
    assert list(kb.jobs) == ["JOB1", "JOB2"]  # the queued request started
    kb.finish("JOB2")
    assert _status(client, hr, b)["index_status"] == "ready"
    assert _status(client, hr, c)["index_status"] == "ready"


def test_revision_keeps_old_version_searchable_until_new_is_ready(client, hr, kb) -> None:  # type: ignore[no-untyped-def]
    v1 = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    _approve(client, hr, v1)
    kb.finish("JOB1")
    _status(client, hr, v1)

    v2 = client.post(f"/api/v1/policies/{v1}/revise", headers=hr["admin"]).json()["id"]
    client.put(f"/api/v1/policies/{v2}", headers=hr["admin"],
               json={"body": LEAVE.replace("20 days", "22 days")})
    _approve(client, hr, v2)

    # v2 is approved but still indexing: answers still come from v1 (Req 2.4).
    mid = _ask(client, hr["employee"], "How many days of annual leave?")
    assert mid["answered"] is True and mid["sources"][0]["version"] == 1

    kb.finish("JOB2")
    assert _status(client, hr, v2)["index_status"] == "ready"
    # The v1 object was removed and a cleanup sync started.
    assert all("/v1/" not in k for k in kb.objects)
    assert kb.running_job() == "JOB3"
    kb.finish("JOB3")
    after = _ask(client, hr["employee"], "How many days of annual leave?")
    assert after["sources"][0]["version"] == 2 and "22 days" in after["answer"]


def test_failed_sync_keeps_previous_version_and_allows_reindex(client, hr, kb, engine) -> None:  # type: ignore[no-untyped-def]
    v1 = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    _approve(client, hr, v1)
    kb.finish("JOB1")
    _status(client, hr, v1)
    v2 = client.post(f"/api/v1/policies/{v1}/revise", headers=hr["admin"]).json()["id"]
    _approve(client, hr, v2)
    kb.finish("JOB2", ok=False)

    failed = _status(client, hr, v2)
    assert failed["index_status"] == "failed" and failed["index_error"]
    still = _ask(client, hr["employee"], "How many days of annual leave?")
    assert still["answered"] is True and still["sources"][0]["version"] == 1  # Req 3.3

    re = client.post(f"/api/v1/policies/{v2}/reindex", headers=hr["admin"])
    assert re.status_code == 200 and re.json()["index_status"] == "indexing"
    kb.finish(kb.running_job() or "")
    assert _status(client, hr, v2)["index_status"] == "ready"

    session = sessionmaker(bind=engine)()
    actions = set(session.execute(select(AuditEvent.action)).scalars().all())
    session.close()
    assert {"policy.approved", "policy.index_failed", "policy.reindex_requested",
            "policy.index_ready"} <= actions


def test_retire_removes_object_and_stops_answers(client, hr, kb) -> None:  # type: ignore[no-untyped-def]
    pid = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    _approve(client, hr, pid)
    kb.finish("JOB1")
    _status(client, hr, pid)
    retired = client.post(f"/api/v1/policies/{pid}/retire", headers=hr["admin"]).json()
    assert retired["status"] == "retired" and retired["index_status"] == "not_indexed"
    assert kb.objects == {}
    # Even before the removal sync finishes (KB still holds stale vectors), the answer-time
    # check refuses the retired version (CB-AC-02).
    stale = _ask(client, hr["employee"], "How many days of annual leave?")
    assert stale["answered"] is False


def test_audience_limits_answers_and_library(client, hr, kb) -> None:  # type: ignore[no-untyped-def]
    pid = _create(client, hr, "SYNTHETIC Recruiter incentive",
                  "SYNTHETIC: Recruiters earn an incentive per joined hire.",
                  audience=["role:recruiter"])
    _approve(client, hr, pid)
    kb.finish("JOB1")
    _status(client, hr, pid)
    q = "What incentive do recruiters earn?"
    assert _ask(client, hr["recruiter"], q)["answered"] is True
    assert _ask(client, hr["employee"], q)["answered"] is False  # CB-AC-04

    # Even if the KB returned it (filter misconfigured), the row check blocks it.
    kb.indexed = {k: type(m)(**{**m.__dict__, "audience": ["everyone"]})
                  for k, m in kb.indexed.items()}
    assert _ask(client, hr["employee"], q)["answered"] is False
    titles = [p["title"] for p in client.get("/api/v1/policies", headers=hr["employee"]).json()]
    assert "SYNTHETIC Recruiter incentive" not in titles


def test_bedrock_failure_falls_back_to_keyword_and_says_so(client, hr, kb, test_settings) -> None:  # type: ignore[no-untyped-def]
    test_settings.hr_chatbot_enabled = True
    pid = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    _approve(client, hr, pid)
    kb.fail_retrieve = True
    answer = _ask(client, hr["employee"], "How many days of annual leave do I get?")
    assert answer["answered"] is True
    assert answer["answered_via"] == "keyword" and answer["smart_search_unavailable"] is True


def test_put_failure_marks_index_failed(client, hr, kb) -> None:  # type: ignore[no-untyped-def]
    kb.fail_put = True
    pid = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    approved = _approve(client, hr, pid)
    assert approved["index_status"] == "failed" and "could not store" in approved["index_error"]


def test_reconcile_restores_missing_and_removes_orphans(client, hr, kb, store, engine) -> None:  # type: ignore[no-untyped-def]
    pid = _create(client, hr, "SYNTHETIC Annual leave", LEAVE)
    _approve(client, hr, pid)
    kb.finish("JOB1")
    _status(client, hr, pid)
    kb.objects.clear()  # lost object
    kb.objects["approved/orphan/x/v1/policy.md"] = next(iter(kb.indexed.values()))

    session = sessionmaker(bind=engine, expire_on_commit=False)()
    notes = kb_service.reconcile(session, kb, load_source=source_loader(store))
    session.commit()
    requests = session.execute(select(KbSyncRequest.reason)).scalars().all()
    session.close()
    assert any("orphan" in n for n in notes) and any("restored" in n for n in notes)
    assert "approved/orphan/x/v1/policy.md" not in kb.objects
    assert any(k.startswith("approved/") for k in kb.objects)
    assert "reconcile" in requests
