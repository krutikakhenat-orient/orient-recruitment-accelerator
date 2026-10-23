"""Pluggable text extractors for supported document types (Req 3.2, 5.3).

Baseline is non-LLM. Each extractor returns plain text plus a method label. Optional
heavy dependencies (PyMuPDF for PDF) are imported lazily so the core app runs without
them; when absent, the extractor reports that OCR/parse is unavailable rather than
failing the whole request.

IMPORTANT (AI safety): extracted text is untrusted data. It is never executed, and it is
never interpreted as instructions. Callers treat it as content only.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass


@dataclass(frozen=True)
class TextExtractionResult:
    text: str
    method: str
    ok: bool
    detail: str = ""


def extract_txt(data: bytes) -> TextExtractionResult:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    return TextExtractionResult(text=text, method="native_text", ok=True)


def extract_docx(data: bytes) -> TextExtractionResult:
    """Extract text from a DOCX (OOXML) file.

    DOCX is a ZIP of XML parts. We read word/document.xml and strip tags. We cap the
    uncompressed size we will read to resist decompression ("zip bomb") attacks.
    """
    max_uncompressed = 50 * 1024 * 1024  # 50 MiB ceiling for the document part
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            try:
                info = zf.getinfo("word/document.xml")
            except KeyError:
                return TextExtractionResult("", "docx_ooxml", ok=False,
                                            detail="word/document.xml not found")
            if info.file_size > max_uncompressed:
                return TextExtractionResult("", "docx_ooxml", ok=False,
                                            detail="document part exceeds safe size limit")
            raw = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        return TextExtractionResult("", "docx_ooxml", ok=False, detail="not a valid DOCX/ZIP")

    xml = raw.decode("utf-8", errors="replace")
    text = _strip_ooxml(xml)
    return TextExtractionResult(text=text, method="docx_ooxml", ok=True)


def extract_pdf(data: bytes) -> TextExtractionResult:
    """Extract text from a PDF using PyMuPDF if installed; otherwise report unavailable."""
    try:
        import fitz  # PyMuPDF  (optional dependency)
    except ImportError:
        return TextExtractionResult(
            "", "pdf_pymupdf", ok=False,
            detail="PDF text extraction requires PyMuPDF (not installed in this environment)",
        )
    try:
        parts: list[str] = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                parts.append(page.get_text())
        return TextExtractionResult(text="\n".join(parts), method="pdf_pymupdf", ok=True)
    except Exception as exc:  # noqa: BLE001 - parser errors must not crash the request
        return TextExtractionResult("", "pdf_pymupdf", ok=False, detail=f"parse error: {exc}")


def _strip_ooxml(xml: str) -> str:
    """Convert OOXML paragraph/break markup to readable text, dropping all other tags."""
    import re

    # Paragraph and line-break tags become newlines; everything else is removed.
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:br\s*/?>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    # Collapse excessive blank lines.
    xml = re.sub(r"\n{3,}", "\n\n", xml)
    return xml.strip()


def extract_text(logical_type: str, data: bytes) -> TextExtractionResult:
    if logical_type == "txt":
        return extract_txt(data)
    if logical_type == "docx":
        return extract_docx(data)
    if logical_type == "pdf":
        return extract_pdf(data)
    if logical_type in {"png", "jpeg"}:
        return TextExtractionResult(
            "", "ocr", ok=False,
            detail="OCR fallback is not available in this environment",
        )
    return TextExtractionResult("", "unknown", ok=False, detail="unsupported type")
