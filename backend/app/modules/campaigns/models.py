"""Campaign ORM model (Req 2.2, 2.3).

The campaign carries its lifecycle `state` plus pointers to the approved, immutable
versions it depends on (JD, rule-set, form, threshold) and the privacy-notice version.
Status is only ever changed through the TransitionService, never via general CRUD.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, OptimisticVersion, Timestamped, UUIDPrimaryKey
from app.modules.campaigns.states import CampaignState


class Campaign(UUIDPrimaryKey, Timestamped, Actioned, OptimisticVersion, Base):
    __tablename__ = "campaign"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position_title: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    number_of_openings: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    work_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)

    hiring_manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    application_opening_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    application_closing_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CampaignState.DRAFT.value, index=True
    )

    # Approved, immutable version pointers (set as the campaign progresses).
    approved_jd_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    approved_rule_set_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    approved_form_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    active_threshold_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    privacy_notice_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retention_policy: Mapped[str | None] = mapped_column(String(64), nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
