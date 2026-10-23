"""API integration tests for Phase 3: public application submission + staff review."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import sessionmaker

from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from app.modules.forms import service as form_service
from app.modules.identity.models import CampaignAssignment
from app.modules.identity.permissions import RoleName
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"
RESUME = b"email: cand@example.com\n5 years of experience\n"

ANSWERS = {
    "full_name": "Synthetic Candidate",
    "email": "cand@example.com",
    "mobile": "+14155550100",
    "current_location": "Mumbai",
    "total_experience_years": "5",
    "notice_period": "30 days",
    "skills": "Python",
    "education": "BSc",
    "candidate_declaration": True,
    "privacy_consent": True,
}


def _seed_open_campaign(engine):  # type: ignore[no-untyped-def]
    """Create an org, an HR user, and an APPLICATIONS_OPEN campaign with an approved form."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        org = make_org(session)
        role = make_role(session, org, RoleName.RECRUITER_ADMIN)
        user = make_user(session, org, roles=[role], password=PASSWORD)

        campaign = Campaign(
            organisation_id=org.id, project_id=uuid.uuid4(),
            name="SYNTHETIC Campaign", position_title="Synthetic Engineer",
            number_of_openings=1, state=CampaignState.APPLICATIONS_OPEN.value,
            privacy_notice_version="v1",
        )
        session.add(campaign)
        session.flush()

        form = form_service.create_form_draft(
            session, organisation_id=org.id, campaign_id=campaign.id, actor_id=user.id
        )
        form_service.approve_form_version(
            session, organisation_id=org.id, form_version_id=form.id, actor_id=user.id
        )
        campaign.approved_form_version_id = form.id

        # Assign the HR user to the campaign for object-level authz.
        session.add(CampaignAssignment(user_id=user.id, campaign_id=campaign.id,
                                       organisation_id=org.id))
        session.commit()
        return user.email, campaign.id
    finally:
        session.close()


def _login(client, email):  # type: ignore[no-untyped-def]
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_public_apply_then_staff_review(client, engine) -> None:
    email, campaign_id = _seed_open_campaign(engine)

    # Public submission (no auth).
    resp = client.post(
        f"/api/v1/public/campaigns/{campaign_id}/apply",
        data={"answers": json.dumps(ANSWERS)},
        files={"resume": ("resume.txt", RESUME, "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "extraction_review"
    application_id = body["application_id"]
    # Candidate response must not leak internal scores/notes.
    assert "score" not in body

    # Staff review the extracted fields (requires auth + object-level authz).
    headers = _login(client, email)
    fields = client.get(f"/api/v1/applications/{application_id}/extracted-fields",
                        headers=headers)
    assert fields.status_code == 200, fields.text
    field_list = fields.json()
    assert any(f["field_name"] == "email" for f in field_list)


def test_public_apply_rejects_malicious_resume(client, engine) -> None:
    _, campaign_id = _seed_open_campaign(engine)
    # A PNG renamed to .pdf fails signature validation.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    resp = client.post(
        f"/api/v1/public/campaigns/{campaign_id}/apply",
        data={"answers": json.dumps(ANSWERS)},
        files={"resume": ("evil.pdf", png, "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_public_apply_requires_consent(client, engine) -> None:
    _, campaign_id = _seed_open_campaign(engine)
    answers = dict(ANSWERS, privacy_consent=False)
    resp = client.post(
        f"/api/v1/public/campaigns/{campaign_id}/apply",
        data={"answers": json.dumps(answers)},
        files={"resume": ("resume.txt", RESUME, "text/plain")},
    )
    assert resp.status_code == 422


def _seed_draft_campaign(engine):  # type: ignore[no-untyped-def]
    """A DRAFT campaign with no approved form — must never appear as an open role.

    Attaches to the SAME (default) organisation created by _seed_open_campaign, so the
    public open-roles endpoint (which reads the default org) sees both and we exercise the
    filter rather than tripping the org unique-name constraint.
    """
    from app.core.errors import NotFoundError
    from app.modules.organisations.repository import get_default_organisation

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        try:
            org = get_default_organisation(session)
        except NotFoundError:
            org = make_org(session)  # no org seeded yet (draft-only test)
        campaign = Campaign(
            organisation_id=org.id, project_id=uuid.uuid4(),
            name="DRAFT Campaign", position_title="Not Yet Open",
            number_of_openings=1, state=CampaignState.DRAFT.value,
        )
        session.add(campaign)
        session.commit()
        return campaign.id
    finally:
        session.close()


def test_public_open_roles_lists_only_open_roles_and_no_internal_fields(client, engine) -> None:
    _, open_campaign_id = _seed_open_campaign(engine)
    _seed_draft_campaign(engine)

    resp = client.get("/api/v1/public/open-roles")
    assert resp.status_code == 200, resp.text
    roles = resp.json()
    ids = {r["id"] for r in roles}
    assert str(open_campaign_id) in ids
    # The draft (no approved form, not open) must NOT be offered.
    assert all(r["title"] != "Not Yet Open" for r in roles)
    # Only candidate-facing fields are exposed — nothing internal leaks.
    sample = next(r for r in roles if r["id"] == str(open_campaign_id))
    assert set(sample) <= {"id", "title", "location", "employment_type", "work_mode"}
    for leaked in ("organisation_id", "state", "approved_form_version_id", "version"):
        assert leaked not in sample


def test_public_role_form_returns_fields_for_open_role(client, engine) -> None:
    _, campaign_id = _seed_open_campaign(engine)
    resp = client.get(f"/api/v1/public/campaigns/{campaign_id}/form")
    assert resp.status_code == 200, resp.text
    form = resp.json()
    keys = {f["key"] for f in form["fields"]}
    assert {"full_name", "email", "resume", "privacy_consent"} <= keys


def test_public_role_form_rejected_for_non_open_campaign(client, engine) -> None:
    campaign_id = _seed_draft_campaign(engine)
    resp = client.get(f"/api/v1/public/campaigns/{campaign_id}/form")
    # Draft campaign is not accepting applications -> validation error, never a usable form.
    assert resp.status_code == 422


def test_submission_routes_to_selected_role_bucket(client, engine) -> None:
    # Submitting via the consolidated flow is just submit-to-chosen-campaign: the resulting
    # application belongs to that campaign bucket.
    email, campaign_id = _seed_open_campaign(engine)
    resp = client.post(
        f"/api/v1/public/campaigns/{campaign_id}/apply",
        data={"answers": json.dumps(ANSWERS)},
        files={"resume": ("resume.txt", RESUME, "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    application_id = resp.json()["application_id"]
    headers = _login(client, email)
    app = client.get(f"/api/v1/applications/{application_id}", headers=headers)
    assert app.status_code == 200, app.text
    assert app.json()["campaign_id"] == str(campaign_id)
