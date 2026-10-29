"""Induction data access. All queries are organisation-scoped."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.induction.models import InductionCompletion, InductionVideo


def get_active_video(
    db: Session, organisation_id: uuid.UUID
) -> InductionVideo | None:
    stmt = (
        select(InductionVideo)
        .where(
            InductionVideo.organisation_id == organisation_id,
            InductionVideo.is_active.is_(True),
        )
        .order_by(InductionVideo.created_at.asc())
    )
    return db.execute(stmt).scalars().first()


def get_completion(
    db: Session,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    video_id: uuid.UUID,
) -> InductionCompletion | None:
    stmt = select(InductionCompletion).where(
        InductionCompletion.organisation_id == organisation_id,
        InductionCompletion.user_id == user_id,
        InductionCompletion.induction_video_id == video_id,
    )
    return db.execute(stmt).scalars().first()


def create_completion(
    db: Session,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    video_id: uuid.UUID,
) -> InductionCompletion:
    completion = InductionCompletion(
        organisation_id=organisation_id,
        user_id=user_id,
        induction_video_id=video_id,
        completed_at=dt.datetime.now(tz=dt.UTC),
    )
    db.add(completion)
    db.flush()
    return completion


def upsert_video(
    db: Session,
    organisation_id: uuid.UUID,
    title: str,
    description: str | None,
    storage_key: str,
    content_type: str,
) -> InductionVideo:
    """Idempotent: reuse the org's existing active video if present, else create it."""
    existing = get_active_video(db, organisation_id)
    if existing is not None:
        return existing
    video = InductionVideo(
        organisation_id=organisation_id,
        title=title,
        description=description,
        storage_key=storage_key,
        content_type=content_type,
        is_active=True,
    )
    db.add(video)
    db.flush()
    return video
