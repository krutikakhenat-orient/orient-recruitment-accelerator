"""Dynamic application form schema models (Req 4.1).

A FormSchema belongs to a campaign and has one or more FormVersions. An approved form
version is immutable. Fields are classified; compensation fields default off; a set of
prohibited fields can never be added (they must not influence screening).
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class FormVersionStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class FieldClass(str, Enum):
    CORE_IDENTITY = "core_identity"
    ELIGIBILITY = "eligibility"
    SKILLS_EXPERIENCE = "skills_experience"
    EDUCATION_CERTIFICATION = "education_certification"
    AVAILABILITY = "availability"
    COMPENSATION = "compensation"
    CONSENT_DECLARATION = "consent_declaration"
    RESUME_ATTACHMENT = "resume_attachment"
    ACCESSIBILITY_ASSISTANCE = "accessibility_assistance"


class FormSchema(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "form_schema"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    versions: Mapped[list[FormVersion]] = relationship(
        back_populates="form_schema", cascade="all, delete-orphan", lazy="selectin"
    )


class FormVersion(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "form_version"

    form_schema_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_schema.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FormVersionStatus.DRAFT.value
    )
    # Whether compensation fields are enabled for this campaign (default off).
    compensation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    form_schema: Mapped[FormSchema] = relationship(back_populates="versions")
    fields: Mapped[list[FormField]] = relationship(
        back_populates="form_version", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_approved(self) -> bool:
        return self.status == FormVersionStatus.APPROVED.value


class FormField(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "form_field"

    form_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_class: Mapped[str] = mapped_column(String(32), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False)  # text, number, date...
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # For a repeating_group field (e.g. education / work history), the column definitions of
    # one row: a list of {"key","label","field_type","required"} dicts. The candidate's
    # answer for such a field is a JSON array of row objects keyed by these sub-field keys.
    item_schema: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)

    form_version: Mapped[FormVersion] = relationship(back_populates="fields")
