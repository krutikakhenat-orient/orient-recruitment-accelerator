"""Dashboard "Jobs you are setting up" overview and the public jobs list. SYNTHETIC data."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import sessionmaker

from app.modules.campaigns.models import Campaign
from app.modules.campaigns.states import CampaignState
from tests.test_check_in_out_api import _login, _seed


def _add_draft_campaign(engine, org_id) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """A job still being set up, NOT assigned to anyone."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as db:
        campaign = Campaign(
            organisation_id=org_id, project_id=uuid.uuid4(),
            name="SYNTHETIC Draft Campaign", position_title="Synthetic Analyst",
            number_of_openings=1, state=CampaignState.DRAFT.value,
        )
        db.add(campaign)
        db.commit()
        return campaign.id


def test_overview_lists_only_the_callers_assigned_jobs(client, engine) -> None:  # type: ignore[no-untyped-def]
    data = _seed(engine)
    _add_draft_campaign(engine, data["org_id"])
    resp = client.get(
        "/api/v1/campaigns/setup-overview", headers=_login(client, "admin@example.com")
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["campaign_id"] for r in rows] == [str(data["campaign_id"])]
    row = rows[0]
    assert row["name"] == "SYNTHETIC Campaign"
    assert row["setup"]["is_open"] is True
    assert {s["key"] for s in row["setup"]["steps"]} == {
        "upload_jd", "approve_jd", "criteria", "form", "open",
    }


def test_overview_is_empty_for_people_who_do_not_set_up_jobs(client, engine) -> None:  # type: ignore[no-untyped-def]
    _seed(engine)
    resp = client.get(
        "/api/v1/campaigns/setup-overview", headers=_login(client, "panel@example.com")
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_public_jobs_list_shows_open_jobs_only(client, engine) -> None:  # type: ignore[no-untyped-def]
    data = _seed(engine)
    draft_id = _add_draft_campaign(engine, data["org_id"])
    roles = client.get("/api/v1/public/open-roles").json()
    ids = {r["id"] for r in roles}
    assert str(data["campaign_id"]) in ids
    assert str(draft_id) not in ids


def test_public_job_shows_approved_jd_only(client, engine) -> None:  # type: ignore[no-untyped-def]
    from app.modules.job_descriptions.models import JDVersion, JobDescription

    data = _seed(engine)
    draft_id = _add_draft_campaign(engine, data["org_id"])
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as db:
        jd = JobDescription(organisation_id=data["org_id"], campaign_id=data["campaign_id"])
        db.add(jd)
        db.flush()
        version = JDVersion(
            job_description_id=jd.id, organisation_id=data["org_id"], version_number=1,
            status="approved", position_title="Synthetic Engineer", department="SYNTHETIC Eng",
            mandatory_skills=["Python"], desirable_skills=["AWS"],
            responsibilities=["Build SYNTHETIC services"], minimum_total_experience_years=2,
            extraction_draft={"internal": "never public"},
        )
        db.add(version)
        db.flush()
        campaign = db.get(Campaign, data["campaign_id"])
        assert campaign is not None
        campaign.approved_jd_version_id = version.id
        db.commit()

    job = client.get(f"/api/v1/public/open-roles/{data['campaign_id']}")
    assert job.status_code == 200, job.text
    body = job.json()
    assert body["must_have_skills"] == ["Python"]
    assert body["nice_to_have_skills"] == ["AWS"]
    assert body["department"] == "SYNTHETIC Eng"
    assert "never public" not in job.text and "extraction" not in job.text
    # A job still being set up is not reachable, and looks like any missing job.
    assert client.get(f"/api/v1/public/open-roles/{draft_id}").status_code == 404
    assert client.get(f"/api/v1/public/open-roles/{uuid.uuid4()}").status_code == 404
