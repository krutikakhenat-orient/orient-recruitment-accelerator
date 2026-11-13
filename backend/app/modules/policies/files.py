"""Safe intake of uploaded policy files (Req 1.1-1.3, 3.6).

Order: size -> extension -> declared MIME -> file signature -> active-content and
decompression checks -> hash -> write to quarantine/ -> malware scan -> text extraction.
A file only leaves quarantine/ (to draft/) after every step passes; on any failure the
quarantine copy is deleted and a plain-language reason is returned.

Security notes:
- Storage keys are generated; the uploaded filename is kept only as a sanitised display
  label and never becomes part of a path (path-traversal defence).
- The file is never executed or rendered. Extracted text is untrusted data.
- DOCX is a ZIP: entry count, total uncompressed size and compression ratio are capped
  (zip-bomb defence) and macro projects are refused.
- PDFs with JavaScript, launch actions or embedded files are refused (active content).
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass

from app.core.errors import ValidationError
from app.modules.documents.scanning import MalwareScanner
from app.modules.documents.storage import ObjectStore
from app.modules.documents.validation import normalise_extension, validate_upload
from app.modules.extraction.text_extractors import extract_text

POLICY_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
_DECLARED_OK = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/x-markdown", "text/plain"},
}
# Browsers sometimes send these for any file; they are not evidence of a mismatch.
_GENERIC_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

_ZIP_MAX_ENTRIES = 2000
_ZIP_MAX_TOTAL = 60 * 1024 * 1024
_ZIP_MAX_RATIO = 100
_PDF_ACTIVE = (b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile")
_MIN_TEXT_CHARS = 20
MAX_BODY_CHARS = 200_000

UNREADABLE_MESSAGE = (
    "We could not read any text in this file. If it is a scanned image, please upload a "
    "version with selectable text (PDF with text, DOCX, TXT or MD)."
)


@dataclass(frozen=True)
class ReceivedFile:
    quarantine_key: str
    display_name: str
    extension: str
    content_type: str
    content_hash: str
    text: str
    size_bytes: int


def safe_display_name(filename: str) -> str:
    base = re.split(r"[\\/]", filename.strip())[-1]
    cleaned = re.sub(r"[^\w .()-]", "_", base).strip(" .")
    return (cleaned or "policy")[:120]


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            entries = zf.infolist()
            if len(entries) > _ZIP_MAX_ENTRIES:
                raise ValidationError("This DOCX file has too many parts to be processed safely.")
            total = sum(e.file_size for e in entries)
            packed = sum(e.compress_size for e in entries) or 1
            if total > _ZIP_MAX_TOTAL or total / packed > _ZIP_MAX_RATIO:
                raise ValidationError(
                    "This DOCX file expands to an unsafe size and was not accepted."
                )
            names = {e.filename.lower() for e in entries}
            if "word/document.xml" not in names:
                raise ValidationError("This file is not a valid Word document.")
            if any(n.endswith("vbaproject.bin") for n in names):
                raise ValidationError(
                    "Word files with macros are not accepted. Save it as a plain .docx first."
                )
    except zipfile.BadZipFile as exc:
        raise ValidationError("This file is not a valid Word document.") from exc


def _check_pdf(data: bytes) -> None:
    if any(marker in data for marker in _PDF_ACTIVE):
        raise ValidationError(
            "This PDF contains scripts, launch actions or embedded files and was not accepted. "
            "Print it to a new PDF and upload that instead."
        )


def _clean_text(text: str) -> str:
    # Drop control characters (keeps newlines and tabs) so stored text is plain data.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()


def validate_policy_file(
    *, filename: str, declared_content_type: str, data: bytes, max_bytes: int
) -> tuple[str, str]:
    """Return (extension, canonical content type) or raise ValidationError."""
    if not data:
        raise ValidationError("The file is empty.")
    if len(data) > max_bytes:
        raise ValidationError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    extension = normalise_extension(filename)
    if extension not in POLICY_EXTENSIONS:
        raise ValidationError("Only PDF, DOCX, TXT and MD files can be uploaded.")
    declared = (declared_content_type or "").split(";")[0].strip().lower()
    if declared not in _GENERIC_TYPES and declared not in _DECLARED_OK[extension]:
        raise ValidationError("The file type does not match its extension.")
    # Signature check reuses the shared validator (.md is checked as plain text).
    probe_name = "upload.txt" if extension == ".md" else f"upload{extension}"
    try:
        validate_upload(filename=probe_name, declared_content_type="", data=data)
    except ValidationError as exc:
        raise ValidationError("The file content does not match its extension.") from exc
    if extension == ".docx":
        _check_docx(data)
    if extension == ".pdf":
        _check_pdf(data)
    return extension, CONTENT_TYPES[extension]


def extract_policy_text(extension: str, data: bytes) -> str:
    if extension in {".txt", ".md"}:
        result = extract_text("txt", data)
    else:
        result = extract_text(extension.lstrip("."), data)
    text = _clean_text(result.text) if result.ok else ""
    if len(text) < _MIN_TEXT_CHARS:
        raise ValidationError(UNREADABLE_MESSAGE)
    return text[:MAX_BODY_CHARS]


def receive_upload(
    *, store: ObjectStore, scanner: MalwareScanner, organisation_id: uuid.UUID,
    filename: str, declared_content_type: str, data: bytes, max_bytes: int,
) -> ReceivedFile:
    extension, content_type = validate_policy_file(
        filename=filename, declared_content_type=declared_content_type, data=data,
        max_bytes=max_bytes,
    )
    quarantine_key = f"quarantine/{organisation_id}/{uuid.uuid4().hex}{extension}"
    store.put(quarantine_key, data, content_type)
    try:
        if not scanner.scan(data).clean:
            raise ValidationError("The file did not pass the security scan and was not saved.")
        text = extract_policy_text(extension, data)
    except Exception:
        store.delete(quarantine_key)
        raise
    return ReceivedFile(
        quarantine_key=quarantine_key, display_name=safe_display_name(filename),
        extension=extension, content_type=content_type,
        content_hash=hashlib.sha256(data).hexdigest(), text=text, size_bytes=len(data),
    )


def draft_key(
    organisation_id: uuid.UUID, policy_id: uuid.UUID, version: int, extension: str
) -> str:
    return f"draft/{organisation_id}/{policy_id}/v{version}/policy{extension}"


def markdown_for(title: str, body: str) -> bytes:
    """Typed-in policies and FAQs are stored as Markdown so they follow the file path (Req 1.6)."""
    return f"# {title.strip()}\n\n{body.strip()}\n".encode()


def extension_of(key: str | None) -> str:
    if not key:
        return ".md"
    ext = normalise_extension(key)
    return ext if ext in POLICY_EXTENSIONS else ".md"
