"""Knowledge Base sync bookkeeping (migration 0014).

Bedrock runs one ingestion job per data source at a time. A request made while a job is
running is queued and merged into the next job, so at most one request per organisation is
``running`` and at most one is ``queued`` (Req 3.4).
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class SyncState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class KbSyncRequest(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "kb_sync_request"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Short, fixed reasons only (approve, retire, reindex, cleanup, reconcile); no free text.
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SyncState.QUEUED.value, index=True
    )
    ingestion_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
