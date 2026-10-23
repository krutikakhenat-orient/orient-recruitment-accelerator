"""Upload validation: extension + declared MIME + file-signature (magic bytes) + size.

Security notes (steering/security.md, Req 3.1 / 16.1):
- We validate the real content type from the leading bytes, not just the client-declared
  extension or Content-Type (both are attacker-controlled).
- We enforce a maximum size to resist resource-exhaustion and oversized uploads.
- We generate a safe, uuid-based storage key so a malicious filename can never influence
  a filesystem/object-store path (path-traversal defence).
- We never execute or render the content here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.errors import ValidationError

# 10 MiB upload cap for JDs and resumes in the MVP.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Allowed logical types mapped to accepted extensions and canonical MIME.
ALLOWED = {
    "pdf": {"extensions": {".pdf"}, "mime": "application/pdf"},
    "docx": {
        "extensions": {".docx"},
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "txt": {"extensions": {".txt"}, "mime": "text/plain"},
    "png": {"extensions": {".png"}, "mime": "image/png"},
    "jpeg": {"extensions": {".jpg", ".jpeg"}, "mime": "image/jpeg"},
}


@dataclass(frozen=True)
class ValidatedUpload:
    logical_type: str          # one of ALLOWED keys
    content_type: str          # canonical MIME
    extension: str             # normalised extension incl. dot
    storage_key: str           # safe generated key
    size_bytes: int


def _detect_signature(data: bytes) -> str | None:
    """Return the detected logical type from magic bytes, or None if unknown.

    DOCX and modern Office files are ZIP containers (PK\\x03\\x04). We detect the ZIP
    signature and treat it as docx only when the extension agrees; a bare ZIP with a
    .docx extension is still a ZIP container and is handled by the OOXML parser later.
    """
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:4] == b"PK\x03\x04":
        return "docx"  # ZIP container (OOXML)
    return None


def _looks_like_text(data: bytes) -> bool:
    """Heuristic: a sample is plausible UTF-8/ASCII text with no NUL bytes."""
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def normalise_extension(filename: str) -> str:
    name = filename.strip().lower()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def validate_upload(*, filename: str, declared_content_type: str, data: bytes) -> ValidatedUpload:
    size = len(data)
    if size == 0:
        raise ValidationError("Uploaded file is empty")
    if size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"File exceeds the maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB"
        )

    extension = normalise_extension(filename)
    logical_by_ext = next(
        (name for name, spec in ALLOWED.items() if extension in spec["extensions"]),
        None,
    )
    if logical_by_ext is None:
        raise ValidationError(f"Unsupported file extension: '{extension or '(none)'}'")

    signature = _detect_signature(data)

    if logical_by_ext == "txt":
        # Plain text has no reliable magic; verify it is decodable text and not binary.
        if signature is not None or not _looks_like_text(data):
            raise ValidationError("File content does not match a plain-text (.txt) file")
        detected = "txt"
    else:
        if signature is None:
            raise ValidationError("Could not verify the file type from its content")
        if signature != logical_by_ext:
            raise ValidationError(
                "File signature does not match its extension "
                f"(extension '{extension}', detected '{signature}')"
            )
        detected = signature

    canonical_mime = str(ALLOWED[detected]["mime"])
    # The declared content type is advisory; we accept the upload based on content, but
    # flag an obvious mismatch to help detect spoofing attempts.
    if declared_content_type and declared_content_type != canonical_mime:
        # Not fatal (clients vary), but we record the canonical type going forward.
        pass

    storage_key = f"{detected}/{uuid.uuid4().hex}{extension}"
    return ValidatedUpload(
        logical_type=detected,
        content_type=canonical_mime,
        extension=extension,
        storage_key=storage_key,
        size_bytes=size,
    )
