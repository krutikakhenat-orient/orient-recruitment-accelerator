"""Domain error types and a consistent, sanitised error envelope.

Every error returned to a client has the shape::

    {"error": {"code": ..., "message": ..., "correlation_id": ..., "details": ...}}

Internal exception messages are never leaked for unexpected (500) errors.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected application errors mapped to HTTP responses."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_error"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """Optimistic-concurrency or duplicate conflicts."""

    status_code = 409
    code = "conflict"


class SeparationOfDutiesError(PermissionDeniedError):
    """Raised when an actor would violate a separation-of-duties control."""

    code = "separation_of_duties"


class InvalidTransitionError(ConflictError):
    """Raised when a state transition is not permitted by the state machine."""

    code = "invalid_transition"


def error_envelope(
    *, code: str, message: str, correlation_id: str | None, details: Any | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "correlation_id": correlation_id}
    if details is not None:
        body["details"] = details
    return {"error": body}
