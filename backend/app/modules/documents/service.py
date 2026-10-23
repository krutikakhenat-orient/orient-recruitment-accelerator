"""Documents application service: safe upload pipeline (Req 3.1, 5.3, 16.1).

Pipeline: validate (ext+MIME+signature+size) -> hash + duplicate detection -> store in
quarantine -> malware scan -> mark clean/infected. A document is only processable once it
reaches CLEAN status. Rejected or infected files are never passed downstream.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.documents.models import Document, DocumentKind, DocumentStatus
from app.modules.documents.scanning import MalwareScanner, default_scanner
from app.modules.documents.storage import ObjectStore, default_object_store
from app.modules.documents.validation import validate_upload


def find_duplicate(
    db: Session, organisation_id: uuid.UUID, kind: DocumentKind, sha256: str
) -> Document | None:
    stmt = select(Document).where(
        Document.organisation_id == organisation_id,
        Document.kind == kind.value,
        Document.sha256 == sha256,
        Document.status == DocumentStatus.CLEAN.value,
    )
    return db.execute(stmt).scalars().first()


def ingest_document(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    kind: DocumentKind,
    filename: str,
    declared_content_type: str,
    data: bytes,
    object_store: ObjectStore | None = None,
    scanner: MalwareScanner | None = None,
) -> Document:
    store = object_store or default_object_store
    scan = scanner or default_scanner

    # 1. Validate type/size/signature; produces a safe storage key.
    validated = validate_upload(
        filename=filename, declared_content_type=declared_content_type, data=data
    )

    # 2. Hash for integrity + duplicate detection.
    sha256 = hashlib.sha256(data).hexdigest()

    # 3. Create the quarantine record and persist the blob under the safe key.
    document = Document(
        organisation_id=organisation_id,
        kind=kind.value,
        status=DocumentStatus.QUARANTINED.value,
        original_filename=filename[:512],
        storage_key=validated.storage_key,
        content_type=validated.content_type,
        size_bytes=validated.size_bytes,
        sha256=sha256,
        created_by=actor_id,
    )
    db.add(document)
    db.flush()
    store.put(validated.storage_key, data, validated.content_type)

    # 4. Scan while quarantined.
    document.status = DocumentStatus.SCANNING.value
    db.flush()
    result = scan.scan(data)
    if result.clean:
        document.status = DocumentStatus.CLEAN.value
        document.scan_result = result.detail
    else:
        document.status = DocumentStatus.INFECTED.value
        document.scan_result = result.detail
        # Remove the infected blob from storage; keep the metadata record for audit.
        store.delete(validated.storage_key)
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="document.ingested",
            entity_type="document",
            entity_id=str(document.id),
            new_state_ref=document.status,
            reason=f"kind={kind.value}; scan={document.scan_result}",
        ),
    )

    if document.status == DocumentStatus.INFECTED.value:
        raise ValidationError("Uploaded file failed the malware scan and was quarantined")

    return document


def get_clean_document(
    db: Session, organisation_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.organisation_id != organisation_id:
        raise ValidationError("Document not found")
    if doc.status != DocumentStatus.CLEAN.value:
        raise ValidationError("Document is not available for processing")
    return doc
