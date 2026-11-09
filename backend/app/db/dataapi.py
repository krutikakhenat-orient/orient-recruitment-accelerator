"""Aurora Data API dialect fix-ups (only for ORA_DATABASE_URL ``postgresql+auroradataapi``).

The upstream ``sqlalchemy-aurora-data-api`` dialect reports native UUID support (inherited from
PGDialect) but the Data API returns UUID columns as plain strings. SQLAlchemy therefore skips its
result conversion and the app receives ``str`` ids where it expects ``uuid.UUID``: identity checks
fail and bulk INSERT ... RETURNING sentinel matching raises "Can't match sentinel values".

This module registers a subclass of the upstream dialect, under the same URL name, whose generic
``Uuid`` type binds values as text cast to ``uuid`` and converts results back to ``uuid.UUID``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import cast, util
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import sqltypes

_REGISTERED = False


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

    globals()["OraAuroraPostgresDataAPIDialect"] = OraAuroraPostgresDataAPIDialect
    registry.register("postgresql.auroradataapi", __name__, "OraAuroraPostgresDataAPIDialect")
    _REGISTERED = True


def register_if_needed(database_url: str) -> None:
    if "auroradataapi" in database_url:
        register_dataapi_dialect()
