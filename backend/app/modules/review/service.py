"""Human-review service (Req 9.1).

Creates review items from a screening run and records reviewer actions. A correction is
captured as a ReviewAction with both the original and corrected values preserved; the
reviewer must supply a reason. Nothing here silently rewrites source records.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.review.models import (
    ReviewAction,
    ReviewActionType,
    ReviewItem,
    ReviewItemStatus,
    ReviewReason,
)
from app.modules.screening.models import CriterionResult, ScreeningRun

# Which review actions advance the candidate's application, and to which state. A review
# action is advisory routing: it moves a flagged candidate FORWARD (interview), PARKS them
# (waitlist / request more info) or CLEARS the flag (resolve back to screened). It never
# rejects — rejection is a post-assessment hiring decision made with approval authority, so
# the Review Queue deliberately has no reject path (state-machine + responsible-ai.md). Each
# mapped transition still goes through the single application TransitionService, which
# enforces the required permission, campaign scoping, a reason and an audit event.
_ACTION_TRANSITIONS: dict[ReviewActionType, ApplicationState] = {
    ReviewActionType.RECOMMEND_INTERVIEW: ApplicationState.INTERVIEW_RECOMMENDED,
    ReviewActionType.RECOMMEND_WAITLIST: ApplicationState.WAITLISTED,
    ReviewActionType.REQUEST_CLARIFICATION: ApplicationState.ADDITIONAL_INFO_REQUESTED,
    ReviewActionType.CONFIRM_EVIDENCE: ApplicationState.SCREENED,
}


def create_items_for_run(db: Session, run: ScreeningRun) -> list[ReviewItem]:
    """Open review items for the criteria in a run that need a human (manual_review).

    Re-evaluation creates a NEW immutable run (Req 11.2); its findings replace the previous
    run's. To avoid the Review Queue accumulating stale rows for the same candidate across
    re-runs, any still-OPEN items from an EARLIER run of this application are marked
    SUPERSEDED first. Past ``ScreeningRun``/``CriterionResult`` rows are untouched — only the
    transient queue items are retired — so prior results remain fully reproducible.
    """
    items: list[ReviewItem] = []
    campaign_id = _campaign_id_for_application(db, run.application_id)
    _supersede_open_items(db, run)
    stmt = select(CriterionResult).where(CriterionResult.screening_run_id == run.id)
    for result in db.execute(stmt).scalars():
        if result.outcome != "manual_review":
            continue
        reason = (
            ReviewReason.MISSING_MANDATORY_EVIDENCE
            if result.mandatory
            else ReviewReason.LOW_CONFIDENCE
        )
        item = ReviewItem(
            organisation_id=run.organisation_id,
            application_id=run.application_id,
            campaign_id=campaign_id,
            reason=reason.value,
            detail=f"{result.criterion_name}: {result.reason}",
            screening_run_id=run.id,
        )
        db.add(item)
        items.append(item)

    # A self-assessment conflict is its own review item so it is visible and actionable in
    # the Review Queue even when no individual criterion routed to manual_review.
    if run.conflict_flagged:
        conflict_item = ReviewItem(
            organisation_id=run.organisation_id,
            application_id=run.application_id,
            campaign_id=campaign_id,
            reason=ReviewReason.CONFLICTING_VALUE.value,
            detail=run.conflict_detail or "Self-assessment conflict with resume evidence.",
            screening_run_id=run.id,
        )
        db.add(conflict_item)
        items.append(conflict_item)

    db.flush()
    return items


def _supersede_open_items(db: Session, run: ScreeningRun) -> None:
    """Retire this application's still-OPEN review items left over from EARLIER runs.

    Only items whose ``screening_run_id`` differs from the current run are closed, so items
    just created for this run are never touched. Reviewer-RESOLVED items keep their status
    (the audit history of a human decision is preserved); only OPEN items are moved to
    SUPERSEDED. This keeps the queue showing exactly one candidate's current findings.
    """
    # Items for the current run are created AFTER this call, so every OPEN item found here
    # belongs to an earlier run (or has no run id). ``col != run.id`` would drop NULLs in
    # SQL, so match "different run id OR no run id" explicitly to catch legacy items too.
    stmt = select(ReviewItem).where(
        ReviewItem.organisation_id == run.organisation_id,
        ReviewItem.application_id == run.application_id,
        ReviewItem.status == ReviewItemStatus.OPEN.value,
        or_(
            ReviewItem.screening_run_id != run.id,
            ReviewItem.screening_run_id.is_(None),
        ),
    )
    for stale in db.execute(stmt).scalars():
        stale.status = ReviewItemStatus.SUPERSEDED.value
    db.flush()


def list_open_items(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[ReviewItem]:
    stmt = select(ReviewItem).where(
        ReviewItem.organisation_id == organisation_id,
        ReviewItem.campaign_id == campaign_id,
        ReviewItem.status == ReviewItemStatus.OPEN.value,
    )
    return list(db.execute(stmt).scalars())


def record_action(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    review_item_id: uuid.UUID,
    action_type: ReviewActionType,
    reason: str,
    actor: AuthenticatedActor,
    original_value: str | None = None,
    corrected_value: str | None = None,
    resolves_item: bool = False,
) -> ReviewAction:
    item = db.get(ReviewItem, review_item_id)
    if item is None or item.organisation_id != organisation_id:
        raise NotFoundError("Review item not found")
    if not reason or not reason.strip():
        raise ValidationError("A reason is required for a review action")
    if action_type is ReviewActionType.CORRECT_VALUE and corrected_value is None:
        raise ValidationError("A corrected_value is required for a correction")

    # If this action is a disposition (interview / waitlist / request-info / resolve), move
    # the application through the single TransitionService FIRST. That call enforces the
    # action's own permission (e.g. interview.approve, waitlist.manage) and campaign
    # assignment, so an actor who may triage review items but lacks approval authority is
    # rejected before anything is written. We only skip the move when the application is not
    # in MANUAL_REVIEW (e.g. an informational note on an already-advanced candidate).
    destination = _ACTION_TRANSITIONS.get(action_type)
    if destination is not None:
        _advance_application(
            db, organisation_id=organisation_id, application_id=item.application_id,
            destination=destination, reason=reason, actor=actor,
        )

    action = ReviewAction(
        review_item_id=item.id,
        organisation_id=organisation_id,
        action_type=action_type.value,
        original_value=original_value,
        corrected_value=corrected_value,
        reason=reason,
        actor_id=actor.user_id,
        resolves_item=resolves_item,
    )
    db.add(action)
    if resolves_item:
        item.status = ReviewItemStatus.RESOLVED.value
        # A resolving disposition (select-for-interview / waitlist) moves the WHOLE
        # application forward, so every other open finding for that candidate is now moot.
        # Close those siblings too, otherwise the candidate keeps reappearing in the queue
        # after being advanced. They are marked SUPERSEDED (closed by a candidate-level
        # disposition) rather than RESOLVED, which is reserved for the item a reviewer acted
        # on. Non-resolving actions (request-info / escalate) stay strictly per-item.
        _close_sibling_items(
            db,
            organisation_id=organisation_id,
            application_id=item.application_id,
            keep_item_id=item.id,
        )
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id, actor_id=actor.user_id,
            action=f"review.action.{action_type.value}", entity_type="review_item",
            entity_id=str(item.id), reason=reason,
        ),
    )
    return action


def _advance_application(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    application_id: uuid.UUID,
    destination: ApplicationState,
    reason: str,
    actor: AuthenticatedActor,
) -> None:
    """Move the reviewed application to ``destination`` via the TransitionService.

    No-op when the application is already past MANUAL_REVIEW, so recording a late note on an
    advanced candidate does not attempt an illegal transition. Any genuinely invalid move
    (or a missing permission) propagates as an error and rolls the action back.
    """
    from app.modules.applications.transition_service import transition as app_transition

    app = db.get(Application, application_id)
    if app is None or app.organisation_id != organisation_id:
        raise NotFoundError("Application not found")
    if app.state != ApplicationState.MANUAL_REVIEW.value:
        return
    app_transition(
        db, application=app, destination=destination, reason=reason, actor=actor,
    )


def _close_sibling_items(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    application_id: uuid.UUID,
    keep_item_id: uuid.UUID,
) -> None:
    """Close an application's OTHER open review items after a candidate-level disposition.

    When a reviewer selects a candidate for interview or waitlists them, the application as
    a whole leaves MANUAL_REVIEW, so any remaining open findings for that candidate are no
    longer actionable. They are marked SUPERSEDED (not RESOLVED — a human did not act on each
    one individually) and the item that was explicitly acted on is left as-is.
    """
    stmt = select(ReviewItem).where(
        ReviewItem.organisation_id == organisation_id,
        ReviewItem.application_id == application_id,
        ReviewItem.status == ReviewItemStatus.OPEN.value,
        ReviewItem.id != keep_item_id,
    )
    for sibling in db.execute(stmt).scalars():
        sibling.status = ReviewItemStatus.SUPERSEDED.value


def _campaign_id_for_application(db: Session, application_id: uuid.UUID) -> uuid.UUID:
    from app.modules.applications.models import Application

    app = db.get(Application, application_id)
    if app is None:
        raise NotFoundError("Application not found")
    return app.campaign_id
