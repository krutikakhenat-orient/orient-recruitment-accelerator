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
# Persist uploaded files (resumes/JDs) to disk for local dev so they survive server
# restarts. Without this the in-memory object store loses every blob on restart and the
# Interview Panel's Resume tab shows "No resume available" for earlier applicants.
_OBJ_DIR = pathlib.Path(__file__).resolve().parent / "local_dev_objectstore"
os.environ.setdefault("ORA_LOCAL_OBJECT_STORE_DIR", str(_OBJ_DIR))

import uvicorn  # noqa: E402

from app.db.models_registry import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def _init_db() -> None:
    # Create every table from the ORM metadata (dev convenience; prod uses Alembic).
    Base.metadata.create_all(engine)
    # create_all() only CREATES missing tables; it never adds new columns to a table that
    # already exists. A local SQLite DB created by an older build can therefore be missing
    # columns added later (e.g. interview_invitation.checked_in_at), which crashes queries
    # with "no such column". Reconcile additively here so an existing local DB self-heals
    # without losing data. Dev-only; production schema changes go through Alembic.
    _reconcile_missing_columns()


def _reconcile_missing_columns() -> None:
    """Additively add any ORM columns missing from existing SQLite tables (dev only).

    For every mapped table, compare the ORM's columns against the live table and issue
    ``ALTER TABLE ... ADD COLUMN`` for anything absent. Only nullable / default-bearing
    columns can be added to a populated table in SQLite, which is exactly how our additive
    migrations are designed. Never drops or alters existing columns, so no data is lost.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text
    from sqlalchemy.schema import CreateColumn

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all already made brand-new tables in full
            live_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in live_cols:
                    continue
                # Render the column DDL (type + nullability/default) the same way the
                # dialect would, so the added column matches the ORM definition.
                col_ddl = CreateColumn(column).compile(dialect=engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN {col_ddl}')
                )
                print(f"[run_local] Added missing column {table.name}.{column.name}")


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
