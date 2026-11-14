"""Regressions found in UAT on 2026-11-14 (all data SYNTHETIC).

1. The ops Lambda's kb_reconcile crashed with NoReferencedTableError: importing only the jobs
   module did not register every ORM model, so flushing a policy_document could not resolve its
   foreign key to organisation. Reproduced in a fresh interpreter, like the Lambda.
2. Policies "synced" while the keyword backend was on (keyword:// marker, no object) kept
   showing "Synced" after the Bedrock knowledge base was switched on.
3. "hi" got "not found"; greetings now get a friendly reply without search or a model call.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.modules.assistant.guard import GREETING_REPLY, THANKS_REPLY, small_talk_reply
from app.modules.assistant.ratelimit import ask_limiter
from app.modules.documents.storage import InMemoryObjectStore
from app.modules.knowledge_base.deps import get_policy_file_store
from app.modules.policies import service as policy_service
from app.modules.policies.models import IndexStatus, PolicyDocument, PolicyStatus
from tests.chatbot_support import login, seed_people
from tests.factories import make_org

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_kb_jobs_register_all_models_in_a_fresh_process(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = tmp_path / "jobs.sqlite3"
    script = (
        "from app.db.base import Base\n"
        "import app.modules.knowledge_base.jobs as jobs\n"  # what ops_handler imports
        "from app.db.session import engine\n"
        "need = {'organisation', 'policy_document', 'kb_sync_request'}\n"
        "missing = need - set(Base.metadata.tables)\n"
        "assert not missing, missing\n"
        "Base.metadata.create_all(engine)\n"
        "print(jobs.run_reconcile())\n"
        "print(jobs.run_index_poll())\n"
    )
    env = {**os.environ, "ORA_ENVIRONMENT": "test", "ORA_DATABASE_URL": f"sqlite:///{db.as_posix()}",
           "ORA_JWT_SECRET": "test-secret-value-at-least-32-chars-long!!"}
    # Runs this interpreter with a fixed, in-test script (no external input): a fresh process
    # is the only way to see which models the jobs module registers on its own.
    proc = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env,  # noqa: S603
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "kb reconcile" in proc.stdout and "kb poll" in proc.stdout


@pytest.mark.parametrize("bedrock_on,expected", [(False, "ready"), (True, "not_indexed")])
def test_keyword_synced_policy_is_not_shown_synced_once_bedrock_is_on(  # type: ignore[no-untyped-def]
    db_session, monkeypatch, bedrock_on, expected
) -> None:
    org = make_org(db_session)
    p = PolicyDocument(organisation_id=org.id, family_id=uuid.uuid4(), title="SYNTHETIC Leave",
                       kind="policy", body="SYNTHETIC: 20 days.", version=1,
                       status=PolicyStatus.APPROVED.value, index_status=IndexStatus.READY.value,
                       approved_key=f"keyword://{uuid.uuid4()}/v1")
    db_session.add(p)
    db_session.flush()
    settings = Settings(environment="test",  # type: ignore[arg-type]
                        jwt_secret="test-secret-value-at-least-32-chars-long!!",
                        hr_chatbot_enabled=bedrock_on, hr_chatbot_backend="bedrock_kb",
                        kb_id="KB1", kb_data_source_id="DS1", kb_docs_bucket="synthetic-bucket")
    monkeypatch.setattr(policy_service, "get_settings", lambda: settings)
    assert policy_service.to_read(p).index_status == expected
    # A real Bedrock object is never treated as stale.
    p.approved_key = "approved/x/y/v1/policy.md"
    assert policy_service.to_read(p).index_status == "ready"


@pytest.mark.parametrize("text,expected", [
    ("hi", GREETING_REPLY), ("Hi!", GREETING_REPLY), ("hello there", GREETING_REPLY),
    ("Good morning", GREETING_REPLY), ("thanks", THANKS_REPLY), ("Thank you!", THANKS_REPLY),
    ("hi, how many leave days do I get?", None), ("What is the leave policy?", None),
    ("history of the company", None),
])
def test_small_talk_detection(text, expected) -> None:  # type: ignore[no-untyped-def]
    assert small_talk_reply(text) == expected


def test_greeting_gets_a_friendly_reply_without_search(client, engine) -> None:  # type: ignore[no-untyped-def]
    ask_limiter.reset()
    seed_people(engine)
    client.app.dependency_overrides[get_policy_file_store] = lambda: InMemoryObjectStore()
    employee = login(client, "employee@example.com")
    body = client.post("/api/v1/assistant/ask", headers=employee, json={"question": "hi"}).json()
    assert body["outcome"] == "greeting" and body["answer"] == GREETING_REPLY
    assert body["route_to_hr"] is False and body["answered_via"] is None
    session = sessionmaker(bind=engine)()
    from app.modules.policies.models import AssistantQueryLog

    logged = session.query(AssistantQueryLog).one()
    session.close()
    assert logged.outcome == "greeting" and logged.retrieved_count is None
