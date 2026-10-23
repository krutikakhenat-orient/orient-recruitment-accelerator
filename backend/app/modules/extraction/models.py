"""ExtractedField ORM model (Req 5.3).

Each field extracted from a candidate document stores its value, provenance (source
document, page, text span), extraction method, confidence, and a SEPARATE verification
state (value/by/at). The original extracted value is never overwritten by a correction;
a correction records a new verified value plus the correction metadata, preserving the
source extraction for audit (Req 9.1).
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, Timestamped, UUIDPrimaryKey


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CORRECTED = "corrected"       # a human replaced the extracted value
    CONFLICT = "conflict"         # extracted value conflicts with candidate-entered value


class ExtractedField(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "extracted_field"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # The value as extracted (immutable record of what the parser produced).
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The human-verified or corrected value (null until verified/corrected).
    verified_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VerificationStatus.UNVERIFIED.value
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def effective_value(self) -> str | None:
        """The value to use downstream: the verified/corrected value if present."""
        return self.verified_value if self.verified_value is not None else self.extracted_value
