"""Scheduled Knowledge Base jobs, run from ``app.ops_handler`` (EventBridge schedule).

- ``run_index_poll``: every few minutes; updates Indexing -> Ready / Index failed and starts
  queued syncs (Req 3.2, 3.4). HR's index-status endpoint also polls on demand.
- ``run_reconcile``: nightly; repairs differences between approved/ and approved policies,
  logging each correction (Req 3.5).
"""

from __future__ import annotations

from app.core.config import get_settings
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
    settings = get_settings()
    db = SessionLocal()
    try:
        kb = build_knowledge_base(settings, db)
        notes = service.reconcile(db, kb, load_source=source_loader(policy_file_store(settings)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return f"kb reconcile: {len(notes)} correction(s)"
