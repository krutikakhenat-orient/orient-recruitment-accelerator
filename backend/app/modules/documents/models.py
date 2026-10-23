"""Document ORM model for safe upload handling (Req 3.1, 5.3, 16.1).

Documents are stored by reference (object-store key), never as inline content in the DB.
Every document passes through quarantine and a scan before it can be processed. The DB
record tracks validation + scan status, file hash (for duplicate detection), and a safe
generated filename. The original client filename is retained for display only and is
never used to build a filesystem path.
"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class DocumentKind(str, Enum):
    JD = "jd"
    RESUME = "resume"


class DocumentStatus(str, Enum):
    QUARANTINED = "quarantined"      # uploaded, awaiting scan
    SCANNING = "scanning"
    CLEAN = "clean"                  # passed scan, safe to process
    INFECTED = "infected"            # scan flagged; never processed
    REJECTED = "rejected"            # failed validation (type/size/signature)


class Document(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "document"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DocumentStatus.QUARANTINED.value
    )

    # Original client-provided filename, retained for display only (never a path).
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # Safe generated storage key (uuid-based); the only name used to reference the blob.
    storage_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 of the file content, used for duplicate detection.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    scan_result: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def content_type_to_logical(self) -> str:
        """Map the canonical stored MIME back to the logical type for extraction."""
        mapping = {
            "application/pdf": "pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "text/plain": "txt",
            "image/png": "png",
            "image/jpeg": "jpeg",
        }
        return mapping.get(self.content_type, "unknown")
