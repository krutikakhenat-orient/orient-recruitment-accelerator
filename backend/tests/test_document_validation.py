"""Tests for upload validation and the quarantine/scan pipeline (Req 3.1, 16.1, AC-19)."""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from app.core.errors import ValidationError
from app.modules.documents.models import DocumentKind, DocumentStatus
from app.modules.documents.scanning import EICAR
from app.modules.documents.service import find_duplicate, ingest_document
from app.modules.documents.storage import InMemoryObjectStore
from app.modules.documents.validation import validate_upload
from tests.factories import make_org

PDF_BYTES = b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TXT_BYTES = b"Position Title: Synthetic Engineer\nMinimum 3 years experience\n"


def _docx_bytes(document_xml: bytes = b"<w:document><w:body></w:body></w:document>") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_accepts_valid_pdf_by_signature() -> None:
    v = validate_upload(filename="jd.pdf", declared_content_type="application/pdf", data=PDF_BYTES)
    assert v.logical_type == "pdf"
    assert v.storage_key.startswith("pdf/")


def test_rejects_extension_signature_mismatch() -> None:
    # A PNG renamed to .pdf must be rejected (signature check).
    with pytest.raises(ValidationError, match="signature"):
        validate_upload(filename="evil.pdf", declared_content_type="application/pdf",
                        data=PNG_BYTES)


def test_rejects_unsupported_extension() -> None:
    with pytest.raises(ValidationError, match="Unsupported file extension"):
        validate_upload(filename="script.exe", declared_content_type="application/octet-stream",
                        data=b"MZ\x90\x00")


def test_rejects_oversized_file() -> None:
    big = b"%PDF" + b"0" * (10 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match="maximum size"):
        validate_upload(filename="big.pdf", declared_content_type="application/pdf", data=big)


def test_rejects_binary_disguised_as_txt() -> None:
    with pytest.raises(ValidationError, match="plain-text"):
        validate_upload(filename="notes.txt", declared_content_type="text/plain",
                        data=b"\x00\x01\x02binary")


def test_ingest_quarantines_then_marks_clean(db_session) -> None:
    org = make_org(db_session)
    store = InMemoryObjectStore()
    doc = ingest_document(
        db_session,
        organisation_id=org.id,
        actor_id=uuid.uuid4(),
        kind=DocumentKind.JD,
        filename="jd.txt",
        declared_content_type="text/plain",
        data=TXT_BYTES,
        object_store=store,
    )
    assert doc.status == DocumentStatus.CLEAN.value
    assert store.exists(doc.storage_key)


def test_ingest_blocks_infected_file(db_session) -> None:
    org = make_org(db_session)
    store = InMemoryObjectStore()
    infected = b"%PDF-1.5\n" + EICAR
    with pytest.raises(ValidationError, match="malware scan"):
        ingest_document(
            db_session,
            organisation_id=org.id,
            actor_id=uuid.uuid4(),
            kind=DocumentKind.JD,
            filename="jd.pdf",
            declared_content_type="application/pdf",
            data=infected,
            object_store=store,
        )


def test_duplicate_detection_by_hash(db_session) -> None:
    org = make_org(db_session)
    store = InMemoryObjectStore()
    doc = ingest_document(
        db_session, organisation_id=org.id, actor_id=uuid.uuid4(), kind=DocumentKind.JD,
        filename="jd.txt", declared_content_type="text/plain", data=TXT_BYTES,
        object_store=store,
    )
    dup = find_duplicate(db_session, org.id, DocumentKind.JD, doc.sha256)
    assert dup is not None
    assert dup.id == doc.id


def test_docx_signature_accepted() -> None:
    v = validate_upload(
        filename="jd.docx",
        declared_content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        data=_docx_bytes(),
    )
    assert v.logical_type == "docx"
