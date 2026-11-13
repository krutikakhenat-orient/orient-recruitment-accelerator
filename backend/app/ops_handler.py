"""AWS Lambda operations entrypoint: run migrations and seed synthetic trial data.

Invoked manually (``aws lambda invoke``) by the deploy script, never exposed over HTTP.
Event shapes:
    {"action": "migrate"}   apply ``alembic upgrade head`` (reviewed, separate release step)
    {"action": "seed"}      seed SYNTHETIC trial data (idempotent); optionally installs the
                            induction video found in the files bucket at ``_seed/<name>``
    {"action": "migrate_and_seed"}  both, in order
    {"action": "purge_recordings"}  delete AI-interview video evidence past its retention date
                                    (audited). Run daily, e.g. from an EventBridge schedule.

Security: the event carries no secrets and no SQL; actions are a closed whitelist.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
from typing import Any

_ACTIONS = {"migrate", "seed", "migrate_and_seed", "purge_recordings"}
_SEED_VIDEO_KEY = "_seed/induction-video.mp4"


def _migrate() -> str:
    from alembic import command
    from alembic.config import Config

    # alembic.ini lives next to the app package inside the image (/var/task).
    ini = pathlib.Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    # The deploy package ships the migration scripts as "migrations" (the name "alembic"
    # would collide with the installed Alembic library). Fall back to the source-tree name
    # so this handler also works when run from the repository.
    scripts = ini.parent / "migrations"
    if not scripts.is_dir():
        scripts = ini.parent / "alembic"
    cfg.set_main_option("script_location", str(scripts))
    command.upgrade(cfg, "head")
    return "migrated to head"


def _stage_seed_video() -> str | None:
    """Copy ``_seed/induction-video.mp4`` from the files bucket to /tmp if present.

    Sets ORA_INDUCTION_VIDEO_PATH so ``seed_developer_video`` installs it. Returns a note
    for the log, or None when no S3 bucket / seed video exists (placeholder is used).
    """
    bucket = os.environ.get("ORA_S3_BUCKET")
    if not bucket:
        return None
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("s3")
    target = pathlib.Path(tempfile.gettempdir()) / "induction-video.mp4"
    try:
        client.download_file(bucket, _SEED_VIDEO_KEY, str(target))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    os.environ["ORA_INDUCTION_VIDEO_PATH"] = str(target)
    return f"induction video staged ({target.stat().st_size} bytes)"


def _seed() -> str:
    from app.cli.seed import seed
    from app.db.session import SessionLocal

    note = _stage_seed_video()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    return "seeded synthetic data" + (f"; {note}" if note else "; placeholder video")


def _purge_recordings() -> str:
    from app.db.session import SessionLocal
    from app.modules.ai_interviews.recording import purge_expired_recordings
    from app.modules.documents.storage import default_object_store

    db = SessionLocal()
    try:
        count = purge_expired_recordings(db, store=default_object_store)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return f"deleted {count} expired interview recording(s)"


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    action = event.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of {sorted(_ACTIONS)}")
    results: list[str] = []
    if action in {"migrate", "migrate_and_seed"}:
        results.append(_migrate())
    if action == "purge_recordings":
        results.append(_purge_recordings())
    if action in {"seed", "migrate_and_seed"}:
        results.append(_seed())
    return {"status": "ok", "result": "; ".join(results)}
