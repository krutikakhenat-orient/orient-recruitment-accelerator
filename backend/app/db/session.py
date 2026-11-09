"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_settings = get_settings()


def _engine_options() -> dict[str, Any]:
    options: dict[str, Any] = {"pool_pre_ping": True, "future": True}
    if _settings.db_null_pool:
        # Serverless hosting: no pooling across invocations (see Settings.db_null_pool).
        options["poolclass"] = NullPool
    if _settings.database_url.startswith("postgresql"):
        # Allow time for a paused serverless database to resume on the first connection.
        if "auroradataapi" not in _settings.database_url:
            # psycopg-specific option. The Aurora Data API dialect (HTTPS, no TCP connection) has no
            # connect_timeout, and resume-from-pause is handled by the Data API itself.
            options["connect_args"] = {"connect_timeout": _settings.db_connect_timeout_seconds}
    return options


engine = create_engine(str(_settings.database_url), **_engine_options())

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session with commit/rollback handling."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
