"""Knowledge Base interface and value types (design.md 2.2).

Both implementations satisfy the same contract so the assistant does not care which one
answered, except to report it honestly (Req 6.3).

Security: every value passed to a Knowledge Base comes from our own database rows; document
text and questions are untrusted DATA and are never interpreted as instructions.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

EVERYONE = "everyone"


class KnowledgeBaseError(Exception):
    """The Knowledge Base could not complete a call (callers fall back to keyword)."""


class KnowledgeBaseBusyError(KnowledgeBaseError):
    """An ingestion job is already running; the sync request must be queued."""


@dataclass(frozen=True)
class AudienceFilter:
    """Which content an asker may receive. Always includes ``everyone``."""

    organisation_id: uuid.UUID
    tags: frozenset[str]

    def allows(self, audience: list[str] | None) -> bool:
        """True if a policy with this audience is visible to the asker."""
        policy_tags = set(audience or []) or {EVERYONE}
        return bool(policy_tags & self.tags)


@dataclass(frozen=True)
class PolicyMetadata:
    """Sidecar metadata stored next to an approved object (kept small: S3 Vectors limits)."""

    organisation_id: uuid.UUID
    policy_id: uuid.UUID
    version: int
    title: str
    kind: str
    audience: list[str]
    effective_date: dt.date | None = None


@dataclass(frozen=True)
class Passage:
    policy_id: uuid.UUID
    version: int
    title: str
    text: str
    score: float
    page: int | None = None


@dataclass(frozen=True)
class SyncHandle:
    job_id: str | None
    # True when the backend indexes synchronously (keyword): nothing to poll.
    complete: bool = False


class SyncState(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class SyncStatus:
    state: SyncState
    error: str | None = None
    failed_documents: int = 0
    details: dict[str, int] = field(default_factory=dict)


class KnowledgeBase(Protocol):
    """Where approved policy text is indexed and searched."""

    name: str  # "keyword" or "bedrock_kb"; recorded as answered_via

    def put_document(
        self, metadata: PolicyMetadata, data: bytes, *, extension: str, content_type: str
    ) -> str:
        """Place an approved version in the data source; returns its object key."""
        ...

    def delete_document(self, key: str) -> None: ...

    def list_documents(self) -> set[str] | None:
        """Keys currently in the data source, or None if the backend has no object store."""
        ...

    def start_sync(self) -> SyncHandle: ...

    def get_sync_status(self, handle: SyncHandle) -> SyncStatus: ...

    def retrieve(self, query: str, audience: AudienceFilter, top_k: int) -> list[Passage]: ...


def approved_key(metadata: PolicyMetadata, extension: str) -> str:
    """Generated object key; the uploaded filename never reaches a storage path."""
    ext = extension if extension in {".pdf", ".docx", ".txt", ".md"} else ".txt"
    return (
        f"approved/{metadata.organisation_id}/{metadata.policy_id}/"
        f"v{metadata.version}/policy{ext}"
    )
