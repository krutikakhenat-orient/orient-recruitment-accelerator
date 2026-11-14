"""Scheduled Knowledge Base jobs, run from ``app.ops_handler`` (EventBridge schedule).

- ``run_index_poll``: every few minutes; updates Indexing -> Ready / Index failed and starts
  queued syncs (Req 3.2, 3.4). HR's index-status endpoint also polls on demand.
- ``run_reconcile``: nightly; repairs differences between approved/ and approved policies,
  logging each correction (Req 3.5).
"""

from __future__ import annotations

from app.core.config import get_settings

# Register EVERY ORM model before any flush. The ops Lambda imports only this module, and
# without the full registry SQLAlchemy cannot resolve policy_document -> organisation
# (NoReferencedTableError; seen in UAT). The web app gets this via main.py.
from app.db import models_registry  # noqa: F401
from app.db.session import SessionLocal
from app.modules.knowledge_base import service
from app.modules.knowledge_base.factory import build_knowledge_base, policy_file_store
from app.modules.policies.service import source_loader


def run_index_poll() -> str:
    settings = get_settings()
    db = SessionLocal()
    try:
        finished = service.poll(db, build_knowledge_base(settings, db))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return f"kb poll: {finished} sync job(s) finished"


def run_reconcile() -> str:
    """Nightly maintenance: settle finished syncs, then repair approved/ (one DB wake-up).

    Scheduled once a day on purpose: every scheduled run wakes the auto-paused Aurora
    cluster, so a frequent poll would remove its idle savings. While HR watches an
    'Indexing' policy, the index-status endpoint polls on demand."""
    settings = get_settings()
    db = SessionLocal()
    try:
        kb = build_knowledge_base(settings, db)
        finished = service.poll(db, kb)
        notes = service.reconcile(db, kb, load_source=source_loader(policy_file_store(settings)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return f"kb reconcile: {finished} sync job(s) settled, {len(notes)} correction(s)"
