"""Rules & thresholds HTTP router (thin).

Authorisation: rule.create to draft, rule.approve to approve (with SoD enforced in the
service), threshold.change to change a threshold (with four-eyes enforced in the service).
All require object-level campaign authorisation.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor
from app.db.session import get_db
from app.modules.identity.permissions import Permission
from app.modules.identity.policy import require_campaign_permission, require_permission
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.rules import service
from app.modules.rules.schemas import (
    PendingRuleSetRead,
    RuleSetFromJdRequest,
    RuleSetRejectRequest,
    RuleSetVersionCreate,
    RuleSetVersionRead,
    ThresholdChangeRequest,
    ThresholdVersionRead,
)

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


@router.get("/rule-sets/versions/pending", response_model=list[PendingRuleSetRead])
def list_pending_rule_sets(
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> list[PendingRuleSetRead]:
    """Draft rule-set versions awaiting the current approver's decision, restricted to the
    campaigns they're assigned to. Requires rule approval permission."""
    require_permission(actor, Permission.RULE_APPROVE)
    versions = service.list_pending_rule_set_versions(
        db, actor.organisation_id, campaign_ids=actor.assigned_campaign_ids
    )
    return [
        PendingRuleSetRead(
            id=v.id,
            rule_set_id=v.rule_set_id,
            campaign_id=v.rule_set.campaign_id,
            name=v.rule_set.name,
            version_number=v.version_number,
            status=v.status,
            rules=v.rules,
        )
        for v in versions
    ]


@router.post("/rule-sets/versions", response_model=RuleSetVersionRead, status_code=201)
def create_rule_set_version(
    payload: RuleSetVersionCreate,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> RuleSetVersionRead:
    require_campaign_permission(actor, Permission.RULE_CREATE, payload.campaign_id)
    version = service.create_rule_set_version(
        db, organisation_id=actor.organisation_id, campaign_id=payload.campaign_id,
        name=payload.name, rules=payload.rules, actor_id=actor.user_id,
    )
    return RuleSetVersionRead.model_validate(version)


@router.post("/rule-sets/versions/from-jd", response_model=RuleSetVersionRead, status_code=201)
def create_rule_set_version_from_jd(
    payload: RuleSetFromJdRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> RuleSetVersionRead:
    """Draft a complete scoring rule-set from the campaign's approved JD: tiered skills
    (mandatory -> Must-Have gate; desirable -> Good-to-Have weighted) PLUS the JD's minimum
    total experience as a weighted criterion, so candidates are scored on skills AND
    experience together. Requires rule.create + campaign access."""
    require_campaign_permission(actor, Permission.RULE_CREATE, payload.campaign_id)
    version = service.create_rule_set_version_from_jd(
        db, organisation_id=actor.organisation_id, campaign_id=payload.campaign_id,
        actor_id=actor.user_id,
    )
    return RuleSetVersionRead.model_validate(version)


@router.post("/rule-sets/versions/{version_id}/approve", response_model=RuleSetVersionRead)
def approve_rule_set_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> RuleSetVersionRead:
    version = service.get_rule_set_version(db, actor.organisation_id, version_id)
    require_campaign_permission(actor, Permission.RULE_APPROVE, version.rule_set.campaign_id)
    approved = service.approve_rule_set_version(
        db, organisation_id=actor.organisation_id, version_id=version_id,
        approver_id=actor.user_id,
    )
    return RuleSetVersionRead.model_validate(approved)


@router.post("/rule-sets/versions/{version_id}/reject", response_model=RuleSetVersionRead)
def reject_rule_set_version(
    version_id: uuid.UUID,
    payload: RuleSetRejectRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> RuleSetVersionRead:
    version = service.get_rule_set_version(db, actor.organisation_id, version_id)
    require_campaign_permission(actor, Permission.RULE_APPROVE, version.rule_set.campaign_id)
    rejected = service.reject_rule_set_version(
        db, organisation_id=actor.organisation_id, version_id=version_id,
        approver_id=actor.user_id, change_reason=payload.change_reason,
    )
    return RuleSetVersionRead.model_validate(rejected)


@router.post("/thresholds/change", response_model=ThresholdVersionRead, status_code=201)
def change_threshold(
    payload: ThresholdChangeRequest,
    db: Session = Depends(get_db),
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> ThresholdVersionRead:
    require_campaign_permission(actor, Permission.THRESHOLD_CHANGE, payload.campaign_id)
    version = service.change_threshold(
        db, organisation_id=actor.organisation_id, campaign_id=payload.campaign_id,
        review_below=payload.review_below,
        recommend_at_or_above=payload.recommend_at_or_above,
        change_reason=payload.change_reason, actor_id=actor.user_id,
        approver_id=payload.approver_id,
    )
    return ThresholdVersionRead.model_validate(version)
