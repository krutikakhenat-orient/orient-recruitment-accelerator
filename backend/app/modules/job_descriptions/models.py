"""Job Description ORM models (Req 3.1-3.3).

A JobDescription is a container owned by a campaign. It has one or more JDVersions. A
version starts as a DRAFT and becomes APPROVED, at which point it is IMMUTABLE: the
service refuses to modify an approved version, and any change must create a new version.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class JDVersionStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class JobDescription(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "job_description"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    versions: Mapped[list[JDVersion]] = relationship(
        back_populates="job_description", cascade="all, delete-orphan", lazy="selectin"
    )


class JDVersion(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "jd_version"

    job_description_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_description.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=JDVersionStatus.DRAFT.value
    )

    # Source document reference (the uploaded, scanned JD file).
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    # Structured content captured/reviewed by a human (the authoritative JD data).
    position_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    number_of_openings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_total_experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum_relevant_experience_years: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    responsibilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    mandatory_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    desirable_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # The extraction suggestion (kept for traceability; never authoritative on its own).
    extraction_draft: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    job_description: Mapped[JobDescription] = relationship(back_populates="versions")

    @property
    def is_approved(self) -> bool:
        return self.status == JDVersionStatus.APPROVED.value
