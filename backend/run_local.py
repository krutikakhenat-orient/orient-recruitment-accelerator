"""Zero-dependency local runner for Orient Recruitment Accelerator.

Runs the full API against a local SQLite database so you can try it on localhost without
installing PostgreSQL/Docker. It:
  1. points the app at a SQLite file (dev only; SQLite is blocked in production),
  2. creates all tables from the ORM models,
  3. seeds synthetic demonstration data,
  4. starts uvicorn on http://localhost:8000.

Usage (from the backend/ directory, with the venv active or via its python):
    python run_local.py

Then open http://localhost:8000/docs for the interactive API, or /health and /ready.

This is for local evaluation only. Production uses PostgreSQL + Alembic migrations
(see docs/deployment.md).
"""

from __future__ import annotations

import os
import pathlib

# Configure the environment BEFORE importing the app so settings pick it up.
_DB_PATH = pathlib.Path(__file__).resolve().parent / "local_dev.sqlite3"
os.environ.setdefault("ORA_ENVIRONMENT", "development")
os.environ.setdefault("ORA_DATABASE_URL", f"sqlite:///{_DB_PATH.as_posix()}")
os.environ.setdefault("ORA_JWT_SECRET", "local-dev-secret-change-me-32-characters!!")

import uvicorn  # noqa: E402

from app.db.models_registry import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def _init_db() -> None:
    # Create every table from the ORM metadata (dev convenience; prod uses Alembic).
    Base.metadata.create_all(engine)


def _seed() -> None:
    from app.cli.seed import seed

    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


def main() -> None:
    print(f"[run_local] Using SQLite database at: {_DB_PATH}")
    _init_db()
    print("[run_local] Schema created.")
    try:
        _seed()
        print("[run_local] Synthetic data seeded.")
    except Exception as exc:  # noqa: BLE001 - seeding is best-effort for local dev
        print(f"[run_local] Seed skipped/failed (continuing): {exc}")
    print("[run_local] Starting API at http://localhost:8000 (docs at /docs)")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
