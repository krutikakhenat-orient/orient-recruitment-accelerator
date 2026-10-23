"""Application ORM model (Req 5.2).

An Application is a candidate's application to ONE campaign. Its ``answers`` are a snapshot
of what the candidate submitted for that campaign and are never rewritten when the master
candidate profile changes. Status moves only through the application TransitionService.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, OptimisticVersion, Timestamped, UUIDPrimaryKey
from app.modules.applications.states import ApplicationState


class Application(UUIDPrimaryKey, Timestamped, Actioned, OptimisticVersion, Base):
    __tablename__ = "application"
    __table_args__ = (
        # A candidate applies to a given campaign at most once.
        UniqueConstraint("campaign_id", "candidate_id", name="uq_application_campaign_candidate"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # The form version the candidate answered (answers are validated against it).
    form_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    # Snapshot of submitted answers for this campaign (never overwritten by profile edits).
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # The resume document for this application (quarantined/scanned Document).
    resume_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApplicationState.SUBMITTED.value, index=True
    )
    disposition_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
