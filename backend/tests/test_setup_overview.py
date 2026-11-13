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
    resp = client.get("/api/v1/campaigns/setup-overview",
                      headers=_login(client, "admin@example.com"))
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
    resp = client.get("/api/v1/campaigns/setup-overview",
                      headers=_login(client, "panel@example.com"))
    assert resp.status_code == 200
    assert resp.json() == []


def test_public_jobs_list_shows_open_jobs_only(client, engine) -> None:  # type: ignore[no-untyped-def]
    data = _seed(engine)
    draft_id = _add_draft_campaign(engine, data["org_id"])
    roles = client.get("/api/v1/public/open-roles").json()
    ids = {r["id"] for r in roles}
    assert str(data["campaign_id"]) in ids
    assert str(draft_id) not in ids
