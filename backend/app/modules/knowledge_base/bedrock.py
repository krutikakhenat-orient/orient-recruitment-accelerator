"""Amazon Bedrock Knowledge Base implementation (S3 data source, S3 Vectors store).

Only the ``approved/`` prefix of the Docs Bucket is the KB data source, so drafts and retired
versions can never be retrieved (Req 2.1). Each object has a ``.metadata.json`` sidecar used
for the organisation and audience filter (Req 4.2).

Not yet verified against a live KB (design.md section 10): ``listContains`` filtering on a
list attribute with an S3 Vectors store, and per-vector metadata size limits. The opt-in
UAT test covers these once Phase 0 is done.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.modules.knowledge_base.types import (
    AudienceFilter,
    KnowledgeBaseBusyError,
    KnowledgeBaseError,
    Passage,
    PolicyMetadata,
    SyncHandle,
    SyncState,
    SyncStatus,
    approved_key,
)

_PAGE_KEY = "x-amz-bedrock-kb-document-page-number"
_RUNNING = {"STARTING", "IN_PROGRESS", "STOPPING"}
_FAILED = {"FAILED", "STOPPED"}


def _client_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return str(code) if code else None
    return None


def build_filter(audience: AudienceFilter) -> dict[str, Any]:
    """Organisation must match AND the policy audience must contain one of the asker's tags."""
    tag_filters: list[dict[str, Any]] = [
        {"listContains": {"key": "audience", "value": tag}} for tag in sorted(audience.tags)
    ]
    audience_filter: dict[str, Any] = (
        tag_filters[0] if len(tag_filters) == 1 else {"orAll": tag_filters}
    )
    return {
        "andAll": [
            {"equals": {"key": "organisation_id", "value": str(audience.organisation_id)}},
            audience_filter,
        ]
    }


class BedrockKnowledgeBase:
    name = "bedrock_kb"

    def __init__(
        self,
        *,
        kb_id: str,
        data_source_id: str,
        bucket: str,
        s3_client: Any,
        agent_client: Any,
        runtime_client: Any,
    ) -> None:
        self._kb_id = kb_id
        self._data_source_id = data_source_id
        self._bucket = bucket
        self._s3 = s3_client
        self._agent = agent_client
        self._runtime = runtime_client

    # ------------------------------------------------------------- data source

    def put_document(
        self, metadata: PolicyMetadata, data: bytes, *, extension: str, content_type: str
    ) -> str:
        key = approved_key(metadata, extension)
        sidecar = {
            "metadataAttributes": {
                "organisation_id": str(metadata.organisation_id),
                "policy_id": str(metadata.policy_id),
                "version": metadata.version,
                "title": metadata.title[:200],
                "kind": metadata.kind,
                "audience": metadata.audience,
                "effective_date": metadata.effective_date.isoformat()
                if metadata.effective_date else "",
            }
        }
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
            self._s3.put_object(
                Bucket=self._bucket, Key=f"{key}.metadata.json",
                Body=json.dumps(sidecar).encode("utf-8"), ContentType="application/json",
            )
        except Exception as exc:  # botocore errors; surfaced as an index failure
            raise KnowledgeBaseError(
                f"could not store approved file ({type(exc).__name__})"
            ) from exc
        return key

    def delete_document(self, key: str) -> None:
        if not key.startswith("approved/"):
            return  # e.g. a keyword:// marker from before the KB was enabled
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
            self._s3.delete_object(Bucket=self._bucket, Key=f"{key}.metadata.json")
        except Exception as exc:
            raise KnowledgeBaseError(
                f"could not delete approved file ({type(exc).__name__})"
            ) from exc

    def list_documents(self) -> set[str] | None:
        keys: set[str] = set()
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": "approved/"}
            if token:
                kwargs["ContinuationToken"] = token
            response = self._s3.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = str(item["Key"])
                if not key.endswith(".metadata.json"):
                    keys.add(key)
            if not response.get("IsTruncated"):
                return keys
            token = response.get("NextContinuationToken")

    # -------------------------------------------------------------------- sync

    def start_sync(self) -> SyncHandle:
        try:
            response = self._agent.start_ingestion_job(
                knowledgeBaseId=self._kb_id, dataSourceId=self._data_source_id,
                # The API requires a 33-256 character token.
                clientToken=f"ora-sync-{uuid.uuid4().hex}",
            )
        except Exception as exc:
            if _client_error_code(exc) in {"ConflictException", "ServiceQuotaExceededException"}:
                raise KnowledgeBaseBusyError("an ingestion job is already running") from exc
            raise KnowledgeBaseError(f"could not start sync ({type(exc).__name__})") from exc
        return SyncHandle(job_id=str(response["ingestionJob"]["ingestionJobId"]))

    def get_sync_status(self, handle: SyncHandle) -> SyncStatus:
        if handle.job_id is None:
            return SyncStatus(state=SyncState.COMPLETE)
        try:
            job = self._agent.get_ingestion_job(
                knowledgeBaseId=self._kb_id, dataSourceId=self._data_source_id,
                ingestionJobId=handle.job_id,
            )["ingestionJob"]
        except Exception as exc:
            raise KnowledgeBaseError(f"could not read sync status ({type(exc).__name__})") from exc
        status = str(job.get("status", ""))
        stats = job.get("statistics") or {}
        failed_docs = int(stats.get("numberOfDocumentsFailed", 0) or 0)
        if status in _RUNNING:
            return SyncStatus(state=SyncState.RUNNING)
        if status in _FAILED:
            reasons = "; ".join(str(r) for r in job.get("failureReasons", []))[:480]
            return SyncStatus(state=SyncState.FAILED, error=reasons or f"sync {status.lower()}")
        return SyncStatus(state=SyncState.COMPLETE, failed_documents=failed_docs)

    # --------------------------------------------------------------- retrieval

    def retrieve(self, query: str, audience: AudienceFilter, top_k: int) -> list[Passage]:
        try:
            response = self._runtime.retrieve(
                knowledgeBaseId=self._kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": top_k,
                        "filter": build_filter(audience),
                    }
                },
            )
        except Exception as exc:
            raise KnowledgeBaseError(f"retrieve failed ({type(exc).__name__})") from exc
        passages: list[Passage] = []
        for item in response.get("retrievalResults", []):
            meta = item.get("metadata") or {}
            try:
                policy_id = uuid.UUID(str(meta["policy_id"]))
                version = int(float(meta["version"]))
            except (KeyError, ValueError, TypeError):
                continue  # not one of ours; never cite it
            page_raw = meta.get(_PAGE_KEY)
            try:
                page = int(float(page_raw)) if page_raw is not None else None
            except (ValueError, TypeError):
                page = None
            passages.append(Passage(
                policy_id=policy_id, version=version, title=str(meta.get("title", ""))[:255],
                text=str((item.get("content") or {}).get("text", ""))[:4000],
                score=float(item.get("score") or 0.0), page=page,
            ))
        return passages
