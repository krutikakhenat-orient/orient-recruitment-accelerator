"""Regression tests for the authenticated resume-download endpoint
(GET /api/v1/documents/applications/{application_id}/resume).

Covers the fixes made for the HR resume download:
  * The endpoint returns the ORIGINAL uploaded bytes and a sensible filename for the
    correct, candidate-specific application.
  * A missing original file is reported as a clear 404 — NOT silently substituted with the
    extracted-text fallback (so extracted text is never passed off as the original).
  * The extracted-text fallback is only served when explicitly requested (?fallback=text)
    and is then clearly labelled (distinct filename + X-Resume-Source header).
  * Object-level access control is enforced (a user assigned to a different campaign, and
    an unauthenticated caller, are refused).

All data is SYNTHETIC. No real candidate information is used.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import sessionmaker

from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.documents import service as document_service
from app.modules.documents.models import DocumentKind
from app.modules.extraction.models import ExtractedField
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"

# A minimal, valid PDF (header + EOF) so upload validation accepts it as a real file.
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _seed(engine):  # type: ignore[no-untyped-def]
    """Org + recruiter-admin assigned to campaign A (with a real ingested resume) + a
    recruiter-admin assigned only to campaign B (for the cross-campaign denial test)."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        org = make_org(session)
        radmin_role = make_role(session, org, RoleName.RECRUITER_ADMIN)
        insider = make_user(session, org, roles=[radmin_role], password=PASSWORD,
                            email="insider@example.com")
        outsider = make_user(session, org, roles=[radmin_role], password=PASSWORD,
                             email="outsider@example.com")

        def _camp(title: str) -> Campaign:
            c = Campaign(
                organisation_id=org.id, project_id=uuid.uuid4(), name=title,
                position_title=title, number_of_openings=1,
                state=CampaignState.APPLICATIONS_OPEN.value, privacy_notice_version="v1",
            )
            session.add(c)
            session.flush()
            return c

        camp_a = _camp("Campaign A")
        camp_b = _camp("Campaign B")
        session.add(CampaignAssignment(user_id=insider.id, campaign_id=camp_a.id,
                                       organisation_id=org.id))
        session.add(CampaignAssignment(user_id=outsider.id, campaign_id=camp_b.id,
                                       organisation_id=org.id))

        # Application WITH an original resume blob (ingested through the real pipeline, so
        # the blob lands in the shared default object store the endpoint reads from).
        resume_doc = document_service.ingest_document(
            session, organisation_id=org.id, actor_id=insider.id,
            kind=DocumentKind.RESUME, filename="Jane_Synthetic_Resume.pdf",
            declared_content_type="application/pdf", data=PDF_BYTES,
        )
        app_with = Application(
            organisation_id=org.id, campaign_id=camp_a.id, candidate_id=uuid.uuid4(),
            form_version_id=uuid.uuid4(), answers={"full_name": "Jane Synthetic"},
            resume_document_id=resume_doc.id, state=ApplicationState.SCREENED.value,
        )
        session.add(app_with)
        session.flush()

        # Application with NO resume document, but WITH extracted resume text on file (so we
        # can prove the text fallback is opt-in only and never the default).
        app_without = Application(
            organisation_id=org.id, campaign_id=camp_a.id, candidate_id=uuid.uuid4(),
            form_version_id=uuid.uuid4(), answers={"full_name": "No File Synthetic"},
            resume_document_id=None, state=ApplicationState.SCREENED.value,
        )
        session.add(app_without)
        session.flush()
        session.add(ExtractedField(
            organisation_id=org.id, application_id=app_without.id,
            field_name="resume_text", extracted_value="EXTRACTED RESUME TEXT CONTENT",
            extraction_method="pdf_text", confidence=1.0,
        ))
        session.flush()

        session.commit()
        return {
            "insider": insider.email, "outsider": outsider.email,
            "app_with_id": str(app_with.id), "app_without_id": str(app_without.id),
            "original_bytes_len": len(PDF_BYTES),
        }
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_returns_original_bytes_and_sensible_filename(client, engine) -> None:
    s = _seed(engine)
    headers = _login(client, s["insider"])
    r = client.get(f"/api/v1/documents/applications/{s['app_with_id']}/resume",
                   headers=headers)
    assert r.status_code == 200, r.text
    # Exact original bytes, verbatim.
    assert r.content == PDF_BYTES
    # Original file source, not the extracted-text fallback.
    assert r.headers.get("X-Resume-Source") == "original-file"
    # Sensible, safe, candidate-specific filename; forced download; no sniffing.
    cd = r.headers.get("Content-Disposition", "")
    assert f"resume-{s['app_with_id']}.pdf" in cd
    assert cd.startswith("attachment")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Content-Type", "").startswith("application/pdf")


def test_missing_original_is_404_not_text_fallback(client, engine) -> None:
    # Default behaviour: no original file -> clear 404, NOT a silent extracted-text download.
    s = _seed(engine)
    headers = _login(client, s["insider"])
    r = client.get(f"/api/v1/documents/applications/{s['app_without_id']}/resume",
                   headers=headers)
    assert r.status_code == 404, r.text
    # The extracted text must NOT have been served under the guise of the original.
    assert "EXTRACTED RESUME TEXT CONTENT" not in r.text


def test_text_fallback_is_opt_in_and_clearly_labelled(client, engine) -> None:
    s = _seed(engine)
    headers = _login(client, s["insider"])
    r = client.get(
        f"/api/v1/documents/applications/{s['app_without_id']}/resume?fallback=text",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    # Clearly labelled as extracted text, never presented as the original file.
    assert r.headers.get("X-Resume-Source") == "extracted-text-fallback"
    assert "EXTRACTED-TEXT" in r.headers.get("Content-Disposition", "")
    body = r.content.decode("utf-8")
    assert "not the original" in body.lower()
    assert "EXTRACTED RESUME TEXT CONTENT" in body


def test_cross_campaign_access_is_denied(client, engine) -> None:
    # A recruiter-admin assigned only to campaign B cannot read campaign A's resume.
    s = _seed(engine)
    headers = _login(client, s["outsider"])
    r = client.get(f"/api/v1/documents/applications/{s['app_with_id']}/resume",
                   headers=headers)
    assert r.status_code == 403, r.text


def test_unauthenticated_access_is_denied(client, engine) -> None:
    s = _seed(engine)
    r = client.get(f"/api/v1/documents/applications/{s['app_with_id']}/resume")
    assert r.status_code in (401, 403), r.text


def test_correct_application_is_served_not_another(client, engine) -> None:
    # The endpoint serves the resume for the EXACT application id requested. Requesting the
    # no-file application must not return the other application's original bytes.
    s = _seed(engine)
    headers = _login(client, s["insider"])
    r = client.get(f"/api/v1/documents/applications/{s['app_without_id']}/resume",
                   headers=headers)
    assert r.status_code == 404
    assert r.content != PDF_BYTES
