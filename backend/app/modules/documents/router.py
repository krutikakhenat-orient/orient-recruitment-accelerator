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

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.applications import service as application_service
from app.modules.documents import service as document_service
from app.modules.documents.models import DocumentKind
from app.modules.documents.storage import default_object_store
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission
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
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> Response:
    """Download the resume for a specific application.

    Authorisation: candidate.view + assignment to the application's campaign (object-level
    authz) — the resume belongs to the selected candidate and to no other. Returns 404 when
    the application has no resume on file or the document is not available (e.g. never
    passed the scan), so callers can show a clear 'resume not available' message.
    """
    app = application_service.get_application(db, actor.organisation_id, application_id)
    require_campaign_permission(actor, Permission.CANDIDATE_VIEW, app.campaign_id)

    if app.resume_document_id is None:
        raise NotFoundError("No resume is on file for this application")

    # Only a CLEAN document is retrievable; get_clean_document raises if missing/unavailable.
    document = document_service.get_clean_document(
        db, actor.organisation_id, app.resume_document_id
    )
    # Defence in depth: a resume document must belong to this organisation and be a resume.
    if document.kind != DocumentKind.RESUME.value:
        raise NotFoundError("No resume is on file for this application")

    try:
        data = default_object_store.get(document.storage_key)
    except KeyError as exc:
        raise NotFoundError("The resume file could not be retrieved") from exc

    suffix = _SAFE_INLINE_SUFFIX.get(document.content_type, "bin")
    # Safe, generated download filename — never the original client path.
    safe_filename = f"resume-{application_id}.{suffix}"
    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            # Force download, never inline render of untrusted content.
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
