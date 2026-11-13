"""One contract suite for both KnowledgeBase implementations (tasks 2.2-2.4).

The keyword KB runs against SQLite. The Bedrock KB runs against botocore Stubber clients,
which also validate every request against the real AWS API model (so the metadata filter
shape is checked). All policy content is SYNTHETIC.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

import botocore.session
import pytest
from botocore.stub import ANY, Stubber

from app.modules.knowledge_base.bedrock import BedrockKnowledgeBase, build_filter
from app.modules.knowledge_base.keyword import KeywordKnowledgeBase
from app.modules.knowledge_base.types import (
    EVERYONE,
    AudienceFilter,
    KnowledgeBaseBusyError,
    KnowledgeBaseError,
    PolicyMetadata,
    SyncState,
    approved_key,
)
from app.modules.policies.models import IndexStatus, PolicyDocument, PolicyStatus
from tests.factories import make_org

BUCKET = "synthetic-docs-bucket"
KB_ID = "KBSYNTH001"
DS_ID = "DSSYNTH001"


def _client(service: str) -> Any:
    return botocore.session.get_session().create_client(
        service, region_name="ap-south-1", aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
    )


def _policy(db, org_id, title, body, audience=None) -> PolicyDocument:  # type: ignore[no-untyped-def]
    p = PolicyDocument(
        organisation_id=org_id, family_id=uuid.uuid4(), title=title, kind="policy", body=body,
        version=1, status=PolicyStatus.APPROVED.value, audience=audience,
        index_status=IndexStatus.READY.value,
    )
    db.add(p)
    db.flush()
    return p


class KeywordHarness:
    name = "keyword"

    def __init__(self, db) -> None:  # type: ignore[no-untyped-def]
        self.kb = KeywordKnowledgeBase(db)

    def expect_put(self) -> None: ...
    def expect_sync(self) -> None: ...
    def expect_retrieve(self, audience: AudienceFilter, visible: list[PolicyDocument]) -> None: ...
    def verify(self) -> None: ...


class BedrockHarness:
    name = "bedrock_kb"

    def __init__(self, db) -> None:  # type: ignore[no-untyped-def]
        self.s3, self.agent, self.runtime = _client("s3"), _client("bedrock-agent"), _client(
            "bedrock-agent-runtime")
        self.stubs = [Stubber(self.s3), Stubber(self.agent), Stubber(self.runtime)]
        for s in self.stubs:
            s.activate()
        self.kb = BedrockKnowledgeBase(
            kb_id=KB_ID, data_source_id=DS_ID, bucket=BUCKET, s3_client=self.s3,
            agent_client=self.agent, runtime_client=self.runtime,
        )

    def expect_put(self) -> None:
        s3 = self.stubs[0]
        s3.add_response("put_object", {}, {"Bucket": BUCKET, "Key": ANY, "Body": ANY,
                                           "ContentType": ANY})
        s3.add_response("put_object", {}, {"Bucket": BUCKET, "Key": ANY, "Body": ANY,
                                           "ContentType": "application/json"})

    def expect_sync(self) -> None:
        now = dt.datetime.now(dt.UTC)
        job = {"knowledgeBaseId": KB_ID, "dataSourceId": DS_ID, "ingestionJobId": "JOB1",
               "status": "STARTING", "startedAt": now, "updatedAt": now}
        self.stubs[1].add_response("start_ingestion_job", {"ingestionJob": job},
                                   {"knowledgeBaseId": KB_ID, "dataSourceId": DS_ID,
                                    "clientToken": ANY})
        done = {**job, "status": "COMPLETE",
                "statistics": {"numberOfDocumentsFailed": 0}}
        self.stubs[1].add_response("get_ingestion_job", {"ingestionJob": done},
                                   {"knowledgeBaseId": KB_ID, "dataSourceId": DS_ID,
                                    "ingestionJobId": "JOB1"})

    def expect_retrieve(self, audience: AudienceFilter, visible: list[PolicyDocument]) -> None:
        results = [{
            "content": {"text": f"{p.body}"},
            "score": 0.82,
            "location": {"type": "S3", "s3Location": {"uri": f"s3://{BUCKET}/approved/x"}},
            "metadata": {"policy_id": str(p.id), "version": float(p.version), "title": p.title,
                         "x-amz-bedrock-kb-document-page-number": 2.0},
        } for p in visible]
        self.stubs[2].add_response(
            "retrieve", {"retrievalResults": results},
            {"knowledgeBaseId": KB_ID, "retrievalQuery": {"text": ANY},
             "retrievalConfiguration": {"vectorSearchConfiguration": {
                 "numberOfResults": ANY, "filter": build_filter(audience)}}},
        )

    def verify(self) -> None:
        for s in self.stubs:
            s.assert_no_pending_responses()


@pytest.fixture(params=["keyword", "bedrock_kb"])
def harness(request, db_session):  # type: ignore[no-untyped-def]
    return KeywordHarness(db_session) if request.param == "keyword" else BedrockHarness(db_session)


def _meta(org_id: uuid.UUID, version: int = 1) -> PolicyMetadata:
    return PolicyMetadata(organisation_id=org_id, policy_id=uuid.uuid4(), version=version,
                          title="SYNTHETIC Leave policy", kind="policy", audience=[EVERYONE])


def test_put_document_returns_a_key_per_version(harness, db_session) -> None:  # type: ignore[no-untyped-def]
    org = make_org(db_session)
    harness.expect_put()
    harness.expect_put()
    m1 = _meta(org.id)
    m2 = PolicyMetadata(**{**m1.__dict__, "version": 2})
    k1 = harness.kb.put_document(m1, b"synthetic text", extension=".txt", content_type="text/plain")
    k2 = harness.kb.put_document(m2, b"synthetic text", extension=".txt", content_type="text/plain")
    assert k1 and k2 and k1 != k2
    harness.verify()


def test_sync_reaches_complete(harness) -> None:  # type: ignore[no-untyped-def]
    harness.expect_sync()
    handle = harness.kb.start_sync()
    status = harness.kb.get_sync_status(handle)
    assert status.state == SyncState.COMPLETE
    harness.verify()


def test_retrieve_identifies_policy_and_version_and_respects_audience(  # type: ignore[no-untyped-def]
    harness, db_session
) -> None:
    org = make_org(db_session)
    open_policy = _policy(db_session, org.id, "SYNTHETIC Annual leave",
                          "Employees get 20 days of annual leave.")
    _policy(db_session, org.id, "SYNTHETIC Recruiter annual leave bonus",
            "Recruiters get 2 extra annual leave days.", audience=["role:recruiter"])
    audience = AudienceFilter(organisation_id=org.id, tags=frozenset({EVERYONE, "role:employee"}))
    harness.expect_retrieve(audience, [open_policy])
    passages = harness.kb.retrieve("How many days of annual leave?", audience, 5)
    assert [p.policy_id for p in passages] == [open_policy.id]
    assert passages[0].version == 1 and passages[0].score > 0
    harness.verify()


# ------------------------------------------------------------- Bedrock only


def test_bedrock_sidecar_carries_filter_metadata() -> None:
    h = BedrockHarness(None)
    org_id = uuid.uuid4()
    meta = PolicyMetadata(organisation_id=org_id, policy_id=uuid.uuid4(), version=3,
                          title="SYNTHETIC Travel", kind="sop", audience=["role:recruiter"],
                          effective_date=dt.date(2026, 1, 1))
    captured: list[dict[str, Any]] = []
    h.s3.meta.events.register("before-parameter-build.s3.PutObject",
                              lambda params, **_: captured.append(dict(params)))
    h.expect_put()
    key = h.kb.put_document(meta, b"%PDF-synthetic", extension=".pdf",
                            content_type="application/pdf")
    assert key == approved_key(meta, ".pdf") and key.startswith("approved/")
    sidecar = json.loads(captured[1]["Body"])["metadataAttributes"]
    assert sidecar["organisation_id"] == str(org_id)
    assert sidecar["audience"] == ["role:recruiter"] and sidecar["version"] == 3
    assert sidecar["effective_date"] == "2026-01-01"


def test_bedrock_sidecar_has_no_empty_values() -> None:
    # Regression from the Phase 0 trial: Bedrock ignores a file whose sidecar has an empty
    # attribute value (e.g. effective_date: "").
    h = BedrockHarness(None)
    meta = PolicyMetadata(organisation_id=uuid.uuid4(), policy_id=uuid.uuid4(), version=1,
                          title="SYNTHETIC", kind="policy", audience=[])
    captured: list[dict[str, Any]] = []
    h.s3.meta.events.register("before-parameter-build.s3.PutObject",
                              lambda params, **_: captured.append(dict(params)))
    h.expect_put()
    h.kb.put_document(meta, b"synthetic", extension=".md", content_type="text/markdown")
    sidecar = json.loads(captured[1]["Body"])["metadataAttributes"]
    assert "effective_date" not in sidecar
    assert all(v not in ("", [], None) for v in sidecar.values())
    assert sidecar["audience"] == [EVERYONE]


def test_bedrock_busy_and_failed_jobs() -> None:
    h = BedrockHarness(None)
    h.stubs[1].add_client_error("start_ingestion_job", service_error_code="ConflictException")
    with pytest.raises(KnowledgeBaseBusyError):
        h.kb.start_sync()
    h.stubs[1].add_client_error("start_ingestion_job", service_error_code="AccessDeniedException")
    with pytest.raises(KnowledgeBaseError):
        h.kb.start_sync()


def test_bedrock_retrieve_ignores_results_without_our_metadata() -> None:
    h = BedrockHarness(None)
    audience = AudienceFilter(organisation_id=uuid.uuid4(), tags=frozenset({EVERYONE}))
    h.stubs[2].add_response("retrieve", {"retrievalResults": [
        {"content": {"text": "stray"}, "score": 0.99, "metadata": {"title": "x"}},
    ]}, None)
    assert h.kb.retrieve("anything", audience, 3) == []


def test_bedrock_retrieve_error_is_a_knowledge_base_error() -> None:
    h = BedrockHarness(None)
    audience = AudienceFilter(organisation_id=uuid.uuid4(), tags=frozenset({EVERYONE}))
    h.stubs[2].add_client_error("retrieve", service_error_code="ThrottlingException")
    with pytest.raises(KnowledgeBaseError):
        h.kb.retrieve("anything", audience, 3)


def test_filter_requires_organisation_and_audience() -> None:
    org = uuid.uuid4()
    single = build_filter(AudienceFilter(organisation_id=org, tags=frozenset({EVERYONE})))
    assert single["andAll"][0] == {"equals": {"key": "organisation_id", "value": str(org)}}
    assert single["andAll"][1] == {"listContains": {"key": "audience", "value": EVERYONE}}
    multi = build_filter(AudienceFilter(organisation_id=org,
                                        tags=frozenset({EVERYONE, "role:recruiter"})))
    assert len(multi["andAll"][1]["orAll"]) == 2
