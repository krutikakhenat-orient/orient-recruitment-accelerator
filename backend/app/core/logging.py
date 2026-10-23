"""Structured, PII-safe logging.

Logs are emitted as single-line JSON with a correlation id. A redaction filter
scrubs values for keys that commonly carry secrets or candidate PII so they never
reach log sinks. This is defence-in-depth: callers must still avoid logging PII.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.core.correlation import get_correlation_id

# Keys whose values must never appear in logs.
_REDACT_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "jwt",
    "ssn",
    "resume",
    "resume_text",
    "email",
    "mobile",
    "phone",
    "full_name",
    "dob",
    "date_of_birth",
}
_REDACTED = "[REDACTED]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        extra = getattr(record, "context", None)
        if isinstance(extra, dict):
            payload["context"] = _redact(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
