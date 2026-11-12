"""Aurora Data API dialect fix-ups (only for ORA_DATABASE_URL ``postgresql+auroradataapi``).

The upstream ``sqlalchemy-aurora-data-api`` dialect reports native UUID support (inherited from
PGDialect) but the Data API returns UUID columns as plain strings. SQLAlchemy therefore skips its
result conversion and the app receives ``str`` ids where it expects ``uuid.UUID``: identity checks
fail and bulk INSERT ... RETURNING sentinel matching raises "Can't match sentinel values".

This module registers a subclass of the upstream dialect, under the same URL name, whose generic
``Uuid`` type binds values as text cast to ``uuid`` and converts results back to ``uuid.UUID``.

It also retries Data API calls while an auto-paused Aurora cluster resumes
(``DatabaseResumingException``, typically 4-30 s). How long a caller waits is set per context
(``resume_wait_limit``): background work (migrations, seeding, the agent webhook) waits the full
budget, while interactive web requests wait only briefly and then report "service starting" so
the browser can show a "We are starting up" screen instead of a blank page.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy import cast, util
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import sqltypes

_REGISTERED = False
_log = logging.getLogger(__name__)

# Full wait budget (25 s): stays under the API Gateway 29 s integration timeout.
_RESUME_DELAYS_SECONDS = (1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0)
RESUMING_ERROR_CODE = "DatabaseResumingException"

# Seconds this context may spend waiting for a resume. None = the full budget.
_resume_wait_limit: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "ora_resume_wait_limit", default=None
)


@contextlib.contextmanager
def resume_wait_limit(seconds: float | None) -> Iterator[None]:
    """Limit how long Data API calls in this context wait for a resuming database.

    ``0`` fails immediately (the first call still starts the resume); ``None`` waits the full
    budget. Applies to the current task/thread context only.
    """
    token = _resume_wait_limit.set(seconds)
    try:
        yield
    finally:
        _resume_wait_limit.reset(token)


def is_database_resuming(exc: BaseException | None) -> bool:
    """True if ``exc`` (or anything it wraps) is the Data API's 'database is resuming' error."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        response = getattr(exc, "response", None)
        if (
            isinstance(response, dict)
            and response.get("Error", {}).get("Code") == RESUMING_ERROR_CODE
        ):
            return True
        # SQLAlchemy wraps DBAPI errors in .orig; Python chains in __cause__ / __context__.
        exc = getattr(exc, "orig", None) or exc.__cause__ or exc.__context__
    return False


class _ResumeRetryingClient:
    """Proxy for a boto3 ``rds-data`` client that retries while Aurora resumes from pause."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            limit = _resume_wait_limit.get()
            waited = 0.0
            for delay in (*_RESUME_DELAYS_SECONDS, None):
                try:
                    return attr(*args, **kwargs)
                except Exception as exc:
                    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                    if code != RESUMING_ERROR_CODE or delay is None:
                        raise
                    if limit is not None and waited + delay > limit:
                        raise  # caller asked not to wait this long; it reports "starting"
                    _log.info("database resuming from auto-pause; retrying in %.0fs", delay)
                    time.sleep(delay)
                    waited += delay
            raise AssertionError("unreachable")

        return call


class _DataApiUuid(sqltypes.Uuid):  # type: ignore[type-arg]
    """Generic Uuid for the Data API: text on the wire, ``uuid.UUID`` in Python."""

    cache_ok = True

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: Any) -> Any:
            return str(value) if value is not None else None

        return process

    def bind_expression(self, bindvalue: Any) -> Any:
        # Data API parameters are untyped text; the column is uuid.
        return cast(bindvalue, PG_UUID)

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        as_uuid = self.as_uuid

        def process(value: Any) -> Any:
            if value is None:
                return None
            parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            return parsed if as_uuid else str(parsed)

        return process


def register_dataapi_dialect() -> None:
    """Register the patched dialect as ``postgresql.auroradataapi`` (idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return
    from sqlalchemy.dialects import registry
    from sqlalchemy_aurora_data_api import AuroraPostgresDataAPIDialect

    class OraAuroraPostgresDataAPIDialect(AuroraPostgresDataAPIDialect):  # type: ignore[misc]
        colspecs = util.update_copy(  # type: ignore[no-untyped-call]
            AuroraPostgresDataAPIDialect.colspecs, {sqltypes.Uuid: _DataApiUuid}
        )
        supports_statement_cache = True

        def connect(self, *cargs: Any, **cparams: Any) -> Any:
            conn = super().connect(*cargs, **cparams)
            # aurora_data_api keeps its boto3 rds-data client on ``_client``.
            conn._client = _ResumeRetryingClient(conn._client)
            return conn

    globals()["OraAuroraPostgresDataAPIDialect"] = OraAuroraPostgresDataAPIDialect
    registry.register("postgresql.auroradataapi", __name__, "OraAuroraPostgresDataAPIDialect")
    _REGISTERED = True


def register_if_needed(database_url: str) -> None:
    if "auroradataapi" in database_url:
        register_dataapi_dialect()
