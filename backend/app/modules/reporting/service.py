"""Reporting service: HR and management dashboards (Req 15.1, 15.2).

Returns aggregated indicators only. The management dashboard suppresses small-group
breakdowns (counts below SMALL_GROUP_FLOOR are reported as the floor marker rather than an
exact small number) to avoid exposing individual candidates. No per-recruiter or
per-interviewer performance rankings are produced (steering/product.md).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.applications.models import Application
from app.modules.campaigns.models import Campaign
from app.modules.review.models import ReviewItem, ReviewItemStatus

# Breakdowns smaller than this are suppressed in management aggregates.
SMALL_GROUP_FLOOR = 5


@dataclass
class HRDashboard:
    active_campaigns: int
    applications_by_state: dict[str, int] = field(default_factory=dict)
    open_review_items: int = 0


@dataclass
class ManagementDashboard:
    open_campaigns: int
    total_applications: int
    interview_funnel: dict[str, int] = field(default_factory=dict)
    selected_candidates: str = "0"  # may be suppressed as "<5"


_ACTIVE_CAMPAIGN_STATES = {
    "published", "applications_open", "applications_closed", "screening",
    "human_review", "interview_planning", "interviewing", "selection_review",
}


def hr_dashboard(db: Session, organisation_id: uuid.UUID) -> HRDashboard:
    active = db.execute(
        select(func.count())
        .select_from(Campaign)
        .where(
            Campaign.organisation_id == organisation_id,
            Campaign.state.in_(_ACTIVE_CAMPAIGN_STATES),
        )
    ).scalar_one()

    by_state: dict[str, int] = {}
    rows = db.execute(
        select(Application.state, func.count())
        .where(Application.organisation_id == organisation_id)
        .group_by(Application.state)
    ).all()
    for state, count in rows:
        by_state[state] = count

    open_reviews = db.execute(
        select(func.count())
        .select_from(ReviewItem)
        .where(
            ReviewItem.organisation_id == organisation_id,
            ReviewItem.status == ReviewItemStatus.OPEN.value,
        )
    ).scalar_one()

    return HRDashboard(
        active_campaigns=active, applications_by_state=by_state,
        open_review_items=open_reviews,
    )


def _suppress(count: int) -> str:
    """Suppress small, potentially identifying counts."""
    if 0 < count < SMALL_GROUP_FLOOR:
        return f"<{SMALL_GROUP_FLOOR}"
    return str(count)


def management_dashboard(db: Session, organisation_id: uuid.UUID) -> ManagementDashboard:
    open_campaigns = db.execute(
        select(func.count())
        .select_from(Campaign)
        .where(
            Campaign.organisation_id == organisation_id,
            Campaign.state.in_(_ACTIVE_CAMPAIGN_STATES),
        )
    ).scalar_one()

    total_apps = db.execute(
        select(func.count())
        .select_from(Application)
        .where(Application.organisation_id == organisation_id)
    ).scalar_one()

    funnel_states = ["interview_recommended", "interview_scheduled", "attended", "assessed"]
    funnel: dict[str, int] = {}
    for state in funnel_states:
        count = db.execute(
            select(func.count())
            .select_from(Application)
            .where(
                Application.organisation_id == organisation_id,
                Application.state == state,
            )
        ).scalar_one()
        funnel[state] = count

    selected = db.execute(
        select(func.count())
        .select_from(Application)
        .where(
            Application.organisation_id == organisation_id,
            Application.state == "selected",
        )
    ).scalar_one()

    return ManagementDashboard(
        open_campaigns=open_campaigns, total_applications=total_apps,
        interview_funnel=funnel, selected_candidates=_suppress(selected),
    )
