"""Documents HTTP router (thin). Secure, authorised resume access.

Files are never exposed via a public bucket URL. A resume is served only through this
authenticated endpoint, scoped to the owning application's campaign (object-level
authorisation), and only when the document passed the malware scan (CLEAN). The response
is a download with a safe generated filename and no inline rendering of untrusted content
(Content-Disposition: attachment, X-Content-Type-Options: nosniff), defending against
rendering active content from an uploaded file (security.md: file upload safety).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.documents import service as document_service
from app.modules.documents.models import DocumentKind
from app.modules.documents.storage import default_object_store
from app.modules.identity.schemas import AuthenticatedActor

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# Only these content types are ever returned for a resume, and always as an attachment.
# Anything else is served as a generic binary download so a browser never tries to render
# untrusted content inline.
_SAFE_INLINE_SUFFIX = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}


@router.get("/applications/{application_id}/resume")
def download_application_resume(
    application_id: uuid.UUID,
    fallback: str | None = Query(
        default=None,
        pattern="^text$",
        description=(
            "Set to 'text' to receive the extracted resume TEXT (clearly labelled, never "
            "the original) when the original file blob is unavailable. Omit to require the "
            "original file and get a 404 if it is missing."
        ),
    ),
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> Response:
    """Download the resume for a specific application.

    Authorisation (object-level): either staff with candidate.view assigned to the
    application's campaign, OR an interview-panel member while the candidate is actively on
    the interview worklist (so the panel's Resume tab works without broad candidate.view).
    The resume belongs to the selected candidate and to no other.

    By default this returns ONLY the original uploaded file and 404s if it is unavailable,
    so extracted text is never mistaken for the original. Pass ``fallback=text`` to opt in
    to the extracted-text fallback (served clearly labelled as extracted text).
    """
    app = application_service.get_application(db, actor.organisation_id, application_id)
    application_service.authorize_candidate_context_read(db, actor=actor, application=app)

    if app.resume_document_id is not None:
        # Only a CLEAN document is retrievable; raises if missing/unavailable.
        document = document_service.get_clean_document(
            db, actor.organisation_id, app.resume_document_id
        )
        # Defence in depth: a resume document must belong to this org and be a resume.
        if document.kind == DocumentKind.RESUME.value:
            try:
                data = default_object_store.get(document.storage_key)
            except KeyError:
                data = None  # blob unavailable (e.g. lost from a non-persistent dev store)
            if data is not None:
                suffix = _SAFE_INLINE_SUFFIX.get(document.content_type, "bin")
                safe_filename = f"resume-{application_id}.{suffix}"
                return Response(
                    content=data,
                    media_type=document.content_type,
                    headers={
                        # Force download, never inline render of untrusted content.
                        "Content-Disposition": f'attachment; filename="{safe_filename}"',
                        "X-Content-Type-Options": "nosniff",
                        "Cache-Control": "no-store",
                        # Signals this IS the original uploaded file (bytes verbatim).
                        "X-Resume-Source": "original-file",
                    },
                )

    # The original file blob is NOT available (no document on file, or the stored blob was
    # lost — e.g. a dev object store that did not persist across restarts).
    #
    # The optional ``fallback=text`` query flag lets a caller that deliberately wants the
    # extracted text (e.g. the Interview Panel's read-only Resume tab) receive it. That
    # fallback is served as a CLEARLY-LABELLED extracted-text file — a distinct filename and
    # an X-Resume-Source header — so it is never mistaken for the original upload. Without
    # the flag (the default, and what the HR "Download résumé" action uses) a missing
    # original returns a clear 404 rather than silently substituting extracted text.
    if fallback == "text":
        resume_text = _extracted_resume_text(db, actor.organisation_id, application_id)
        if resume_text:
            banner = (
                "NOTE: The original resume file is not available. The following is the "
                "plain TEXT extracted from the resume at upload time, not the original "
                "document.\n"
                "----------------------------------------------------------------------\n\n"
            )
            body = (banner + resume_text).encode("utf-8")
            return Response(
                content=body,
                media_type="text/plain; charset=utf-8",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="resume-{application_id}-EXTRACTED-TEXT.txt"'
                    ),
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "no-store",
                    # Signals this is NOT the original file — extracted text only.
                    "X-Resume-Source": "extracted-text-fallback",
                },
            )

    # No original file available (and no text fallback requested / none stored): a clear
    # missing-original response so a caller never mistakes extracted text for the original.
    raise NotFoundError(
        "The original resume file is not available for this application."
    )


def _extracted_resume_text(
    db: Session, organisation_id: uuid.UUID, application_id: uuid.UUID
) -> str | None:
    """Return the stored extracted resume text for an application, if any.

    Used as a fallback for the resume download when the original file blob is unavailable.
    The text was extracted at ingest time for screening and is stored as the ``resume_text``
    extracted field."""
    from sqlalchemy import select

    from app.modules.extraction.models import ExtractedField

    field = db.execute(
        select(ExtractedField).where(
            ExtractedField.organisation_id == organisation_id,
            ExtractedField.application_id == application_id,
            ExtractedField.field_name == "resume_text",
        )
    ).scalars().first()
    if field is None:
        return None
    text = field.effective_value or ""
    return text if text.strip() else None
