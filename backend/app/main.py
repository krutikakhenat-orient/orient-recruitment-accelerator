"""FastAPI application entrypoint.

Wires middleware (correlation id, security headers), restricted CORS, consistent
error handling, health/readiness endpoints, and module routers. Business logic lives
in services, never here.
"""

from __future__ import annotations

import logging

import jwt
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Environment, get_settings
from app.core.correlation import get_correlation_id, new_correlation_id, set_correlation_id
from app.core.errors import AppError, error_envelope
from app.core.logging import configure_logging, get_logger
from app.db.session import engine
from app.modules.applications.router import public_router as applications_public_router
from app.modules.applications.router import router as applications_router
from app.modules.assessments.router import router as assessments_router
from app.modules.audit.router import router as audit_router
from app.modules.campaigns.router import router as campaigns_router
from app.modules.candidates.router import router as candidates_router
from app.modules.decisions.router import router as decisions_router
from app.modules.dev.router import router as dev_router
from app.modules.documents.router import router as documents_router
from app.modules.forms.router import router as forms_router
from app.modules.identity.router import router as identity_router
from app.modules.interviews.router import router as interviews_router
from app.modules.job_descriptions.router import router as jd_router
from app.modules.privacy.router import router as privacy_router
from app.modules.projects.router import router as projects_router
from app.modules.reporting.router import router as reports_router
from app.modules.review.router import router as reviews_router
from app.modules.rules.router import router as rules_router
from app.modules.screening.router import router as screening_router
from app.modules.talent_pool.router import router as talent_pool_router
from app.modules.waitlist.router import router as waitlist_router

configure_logging()
logger = get_logger("app")


# Swagger UI / ReDoc load assets from a CDN; the docs routes need a relaxed CSP.
# This only applies to the interactive docs pages and only in non-production
# environments (docs are disabled entirely in production).
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_SWAGGER_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' https://fastapi.tiangolo.com data:; "
    "worker-src 'self' blob:"
)


class CorrelationAndSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("X-Correlation-ID") or new_correlation_id()
        set_correlation_id(correlation_id)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        # Security headers (defence in depth; proxy may also set these).
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        settings = get_settings()
        if not settings.is_production_like and request.url.path in _DOCS_PATHS:
            response.headers["Content-Security-Policy"] = _SWAGGER_CSP
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        if settings.is_production_like:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    docs_url = None if settings.is_production_like else "/docs"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=None,
    )

    app.add_middleware(CorrelationAndSecurityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID", "Idempotency-Key"],
    )

    _register_exception_handlers(app)
    _register_routers(app)
    # Dev-only conveniences are registered only outside production-like environments.
    if not settings.is_production_like:
        app.include_router(dev_router)
    _register_health(app, settings_environment=settings.environment)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(
                code=exc.code,
                message=exc.message,
                correlation_id=get_correlation_id(),
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_envelope(
                code="validation_error",
                message="Request validation failed",
                correlation_id=get_correlation_id(),
                details=exc.errors(),
            ),
        )

    @app.exception_handler(jwt.PyJWTError)
    async def _jwt_error(_: Request, __: jwt.PyJWTError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=error_envelope(
                code="authentication_error",
                message="Invalid or expired token",
                correlation_id=get_correlation_id(),
            ),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internal details for unexpected errors.
        logger.error("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_envelope(
                code="internal_error",
                message="An unexpected error occurred",
                correlation_id=get_correlation_id(),
            ),
        )


def _register_routers(app: FastAPI) -> None:
    app.include_router(identity_router)
    app.include_router(audit_router)
    app.include_router(projects_router)
    app.include_router(campaigns_router)
    app.include_router(jd_router)
    app.include_router(forms_router)
    app.include_router(candidates_router)
    app.include_router(applications_router)
    app.include_router(applications_public_router)
    app.include_router(documents_router)
    app.include_router(rules_router)
    app.include_router(screening_router)
    app.include_router(reviews_router)
    app.include_router(interviews_router)
    app.include_router(assessments_router)
    app.include_router(decisions_router)
    app.include_router(waitlist_router)
    app.include_router(talent_pool_router)
    app.include_router(privacy_router)
    app.include_router(reports_router)


def _register_health(app: FastAPI, settings_environment: Environment) -> None:
    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings_environment.value}

    @app.get("/ready", tags=["system"])
    def ready() -> dict[str, str]:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - readiness must report, not crash
            logger.warning("Readiness check failed", exc_info=exc)
            return {"status": "degraded", "database": "unavailable"}
        return {"status": "ready", "database": "ok"}


app = create_app()

logging.getLogger("app").info("Application initialised")
