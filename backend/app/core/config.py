"""Application configuration with startup validation.

Settings come from the environment (and an optional .env file for local dev only).
Secrets must never be hard-coded. In non-development environments the application
refuses to start with insecure default secrets (see ``validate_production_safety``).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A sentinel used only for local development. Rejected outside development.
_DEV_ONLY_SECRET = "dev-only-change-me"  # noqa: S105  (clearly flagged, dev-only sentinel)


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ORA_",
        extra="ignore",
    )

    # --- Environment ---
    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "Orient Recruitment Accelerator"

    # --- Database ---
    # Any SQLAlchemy URL. PostgreSQL is the production target; SQLite is accepted for
    # local, dependency-free runs. ``validate_production_safety`` blocks SQLite in
    # production-like environments.
    database_url: str = "postgresql+psycopg://ora:ora@localhost:5432/ora"

    # --- Security / tokens ---
    jwt_secret: str = _DEV_ONLY_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # 15 minutes (short-lived)
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14  # 14 days
    password_reset_ttl_seconds: int = 60 * 30

    # --- Auth hardening ---
    max_failed_logins: int = 5
    lockout_seconds: int = 60 * 15

    # --- CORS (restricted) ---
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- Feature flags ---
    llm_adapter_enabled: bool = False  # AI is advisory-only and off by default

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production_like(self) -> bool:
        return self.environment in {Environment.STAGING, Environment.PRODUCTION}

    def validate_production_safety(self) -> None:
        """Fail fast if insecure defaults are used in production-like environments."""
        if not self.is_production_like:
            return
        problems: list[str] = []
        if self.jwt_secret == _DEV_ONLY_SECRET or len(self.jwt_secret) < 32:
            problems.append("ORA_JWT_SECRET must be a strong, non-default value (>=32 chars).")
        if any("localhost" in origin for origin in self.cors_allowed_origins):
            problems.append("ORA_CORS_ALLOWED_ORIGINS must not include localhost in production.")
        if self.database_url.startswith("sqlite"):
            problems.append("SQLite is not permitted in production; use PostgreSQL.")
        if problems:
            raise RuntimeError(
                "Insecure configuration for a production-like environment: "
                + "; ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production_safety()
    return settings
