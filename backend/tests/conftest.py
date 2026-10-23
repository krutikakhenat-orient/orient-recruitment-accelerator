"""Shared pytest fixtures.

Tests use an in-memory SQLite database for speed and isolation. The ORM uses
database-neutral types (Uuid, JSON) so the same models run on SQLite and PostgreSQL.
A fresh schema is created per test for isolation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("ORA_ENVIRONMENT", "test")
os.environ.setdefault("ORA_JWT_SECRET", "test-secret-value-at-least-32-chars-long!!")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import settings_dep  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.models_registry import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db_session(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="test",  # type: ignore[arg-type]
        jwt_secret="test-secret-value-at-least-32-chars-long!!",
    )


@pytest.fixture
def client(engine, test_settings) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    def _get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[settings_dep] = lambda: test_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
