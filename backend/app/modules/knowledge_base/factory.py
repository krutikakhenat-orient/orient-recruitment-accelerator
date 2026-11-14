"""Choose the Knowledge Base for a request (``ORA_HR_CHATBOT_BACKEND``)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.documents.storage import ObjectStore, S3ObjectStore, default_object_store
from app.modules.knowledge_base.bedrock import BedrockKnowledgeBase
from app.modules.knowledge_base.keyword import KeywordKnowledgeBase
from app.modules.knowledge_base.types import KnowledgeBase


@lru_cache(maxsize=8)
def _client(service: str, region: str) -> Any:
    import boto3  # lazy: only needed when the Bedrock backend is on

    return boto3.client(service, region_name=region)


def bedrock_runtime_client(settings: Settings) -> Any:
    return _client("bedrock-runtime", settings.kb_region)


def build_knowledge_base(settings: Settings, db: Session) -> KnowledgeBase:
    """Bedrock only when switched on and fully configured; keyword otherwise (Req 6.1)."""
    if not settings.bedrock_kb_active:
        return KeywordKnowledgeBase(db)
    assert settings.kb_id and settings.kb_data_source_id and settings.kb_docs_bucket
    return BedrockKnowledgeBase(
        kb_id=settings.kb_id, data_source_id=settings.kb_data_source_id,
        bucket=settings.kb_docs_bucket,
        s3_client=_client("s3", settings.kb_region),
        agent_client=_client("bedrock-agent", settings.kb_region),
        runtime_client=_client("bedrock-agent-runtime", settings.kb_region),
    )


@lru_cache(maxsize=4)
def _bucket_store(bucket: str) -> S3ObjectStore:
    return S3ObjectStore(bucket)


def policy_file_store(settings: Settings) -> ObjectStore:
    """Where quarantine/ and draft/ copies of policy files live (the Docs Bucket in AWS)."""
    if settings.kb_docs_bucket:
        return _bucket_store(settings.kb_docs_bucket)
    return default_object_store
