"""Rules & thresholds lookup helpers (approved versions by campaign)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.rules.models import (
    ApprovalStatus,
    RuleSet,
    RuleSetVersion,
    ThresholdSet,
    ThresholdVersion,
)


def latest_approved_rule_set_version(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> RuleSetVersion | None:
    stmt = (
        select(RuleSetVersion)
        .join(RuleSet, RuleSet.id == RuleSetVersion.rule_set_id)
        .where(
            RuleSet.organisation_id == organisation_id,
            RuleSet.campaign_id == campaign_id,
            RuleSetVersion.status == ApprovalStatus.APPROVED.value,
        )
        .order_by(RuleSetVersion.version_number.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def latest_approved_threshold_version(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> ThresholdVersion | None:
    stmt = (
        select(ThresholdVersion)
        .join(ThresholdSet, ThresholdSet.id == ThresholdVersion.threshold_set_id)
        .where(
            ThresholdSet.organisation_id == organisation_id,
            ThresholdSet.campaign_id == campaign_id,
            ThresholdVersion.status == ApprovalStatus.APPROVED.value,
        )
        .order_by(ThresholdVersion.version_number.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()
