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

    # Serverless (Lambda) hosting: every invocation may run in a fresh container, so a
    # per-process connection pool only wastes database connections. NullPool opens and
    # closes a connection per use. ``db_connect_timeout_seconds`` is generous because an
    # auto-paused Aurora Serverless v2 cluster can take ~15s to resume on first connect.
    db_null_pool: bool = False
    db_connect_timeout_seconds: int = 30

    # --- Object storage ---
    # When set, files (resumes, JDs, induction video) are stored in this private S3 bucket.
    # When unset, the in-memory / local-disk store is used (local dev and tests).
    s3_bucket: str | None = None
    # Lifetime of the short-lived signed link used to play the induction video.
    signed_url_ttl_seconds: int = 900

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

    # Public base URL of the FRONTEND SPA, used to build absolute links in generated
    # artifacts (e.g. the Excel export's per-candidate "Download Resume" hyperlink). It must
    # point at the app UI, never at a storage bucket; the link lands on an authenticated SPA
    # route, so no public/signed file URL is ever emitted. Override per environment.
    app_base_url: str = "http://localhost:5173"

    # --- Feature flags ---
    llm_adapter_enabled: bool = False  # AI is advisory-only and off by default

    # --- AI voice interview (interview-agent) ---
    # Off by default (responsible-ai.md): the platform runs fully without the agent. The
    # agent is advisory only; it never changes an application's state or produces a verdict.
    ai_interview_enabled: bool = False
    # How the backend reaches the agent: "http" (local `interview-agent` on a URL),
    # "agentcore" (deployed on Amazon Bedrock AgentCore Runtime), or "fake" (tests only).
    ai_interview_agent_mode: str = "http"
    ai_interview_agent_base_url: str = "http://localhost:8080"
    # URL the CANDIDATE'S BROWSER opens for the live audio socket in "http" mode. In
    # "agentcore" mode a short-lived SigV4 pre-signed URL is minted instead.
    ai_interview_agent_ws_url: str = "ws://localhost:8080/ws"
    ai_interview_agentcore_arn: str | None = None
    ai_interview_agentcore_region: str = "ap-south-1"
    # Shared secret the agent uses to HMAC-sign the result webhook. Required when enabled.
    ai_interview_webhook_secret: str | None = None
    ai_interview_webhook_tolerance_seconds: int = 300
    # Candidate link lifetime once a human has approved the questions.
    ai_interview_link_ttl_seconds: int = 60 * 60 * 24 * 7
    ai_interview_max_starts: int = 3
    # Total interview attempts per application, including retries a recruiter offers after
    # an attempt ended early. Each attempt is a separate record; earlier ones are kept.
    ai_interview_max_attempts: int = 3
    ai_interview_agent_timeout_seconds: int = 60

    # --- AI interview video evidence (off by default) ---
    # Records the candidate's camera during the voice interview as EVIDENCE ONLY for a human
    # reviewer. Nothing analyses the video (no face, emotion, gaze or appearance processing;
    # responsible-ai.md). It needs a separate, explicit consent and the candidate can decline
    # and still take the voice interview. Viewing needs candidate.view_pii and is audited.
    ai_interview_video_enabled: bool = False
    ai_interview_video_retention_days: int = 30
    # One upload is ~10 s of 480p video (~0.7 MB). The cap keeps a single request well under
    # the serverless payload limit (6 MB, base64-encoded by API Gateway).
    ai_interview_video_max_chunk_bytes: int = 3_000_000
    ai_interview_video_max_total_bytes: int = 400_000_000
    # How long the browser's upload token works after the interview starts.
    ai_interview_video_upload_window_seconds: int = 2 * 60 * 60

    # --- HR policy chatbot (Bedrock Knowledge Base; off by default) ---
    # The keyword assistant always works. "bedrock_kb" is used only when the chatbot is
    # enabled AND the KB settings below are present; otherwise answers fall back to keyword.
    # Answers are information from approved policy only and never drive an HR decision.
    hr_chatbot_enabled: bool = False
    hr_chatbot_backend: str = "keyword"  # "keyword" | "bedrock_kb"
    kb_id: str | None = None
    kb_data_source_id: str | None = None
    # Private Docs Bucket holding quarantine/, draft/ and approved/ (approved/ is the only
    # KB data source). When unset, policy files use the default object store.
    kb_docs_bucket: str | None = None
    kb_region: str = "ap-south-1"
    hr_chatbot_model_id: str | None = None
    guardrail_id: str | None = None
    guardrail_version: str = "DRAFT"
    # Minimum Bedrock retrieval score (0..1) for a passage to be used in an answer. Phase 0
    # trial (Titan Embed V2, S3 Vectors, cosine): relevant passages 0.73-0.85, unrelated
    # 0.49-0.60. Retune with the real policy set (tasks.md 7.4).
    chatbot_min_score: float = Field(default=0.65, ge=0.0, le=1.0)
    chatbot_top_k: int = Field(default=5, ge=1, le=20)
    # Per-user and per-client-address limit on /assistant/ask (requests per minute).
    chatbot_rate_limit_per_minute: int = Field(default=20, ge=1, le=600)
    # Policy upload size cap (bytes). Cannot exceed the shared upload validator's 10 MiB cap.
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)

    @property
    def bedrock_kb_active(self) -> bool:
        """True only when the chatbot is on, set to Bedrock, and fully configured."""
        return (
            self.hr_chatbot_enabled
            and self.hr_chatbot_backend == "bedrock_kb"
            and bool(self.kb_id and self.kb_data_source_id and self.kb_docs_bucket)
            and bool(self.hr_chatbot_model_id)
        )

    # --- Notifications (email / WhatsApp) ---
    # Every channel is "unconfigured" by default so the product never claims a message was
    # sent when no provider exists. Modes:
    #   unconfigured - nothing is sent; the message is recorded with a manual-send fallback.
    #   simulate     - local demo: the message is recorded as "simulated" (no real delivery).
    #   smtp         - (email only) deliver through an SMTP server, e.g. the MailHog dev sandbox.
    # WhatsApp has no live provider yet: it supports "unconfigured" and "simulate" only
    # (a WhatsApp Business provider account and approved templates are needed first).
    notification_email_mode: str = "unconfigured"
    notification_whatsapp_mode: str = "unconfigured"
    notification_smtp_host: str = "localhost"
    notification_smtp_port: int = 1025
    notification_sender_address: str = "no-reply@orient.local"
    # Public link lifetime for candidate interview-confirmation links.
    confirmation_link_ttl_hours: int = 72

    # --- Campaign publication ---
    # Organisation privacy-notice version attached to a campaign when HR opens it for
    # applications and none was set explicitly. Candidates consent against this version, so
    # changing the notice text should bump this value (the consent record stores it).
    default_privacy_notice_version: str = "v1"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("hr_chatbot_backend")
    @classmethod
    def _check_chatbot_backend(cls, value: str) -> str:
        if value not in {"keyword", "bedrock_kb"}:
            raise ValueError("ORA_HR_CHATBOT_BACKEND must be 'keyword' or 'bedrock_kb'")
        return value

    def chatbot_config_problems(self) -> list[str]:
        """Missing settings when the Bedrock chatbot is switched on (checked at startup)."""
        if not (self.hr_chatbot_enabled and self.hr_chatbot_backend == "bedrock_kb"):
            return []
        required = {
            "ORA_KB_ID": self.kb_id,
            "ORA_KB_DATA_SOURCE_ID": self.kb_data_source_id,
            "ORA_KB_DOCS_BUCKET": self.kb_docs_bucket,
            "ORA_HR_CHATBOT_MODEL_ID": self.hr_chatbot_model_id,
        }
        return [f"{name} must be set when ORA_HR_CHATBOT_BACKEND=bedrock_kb."
                for name, value in required.items() if not value]

    @property
    def is_production_like(self) -> bool:
        return self.environment in {Environment.STAGING, Environment.PRODUCTION}

    def validate_production_safety(self) -> None:
        """Fail fast if insecure defaults are used in production-like environments."""
        if not self.is_production_like:
            return
        problems: list[str] = list(self.chatbot_config_problems())
        if self.jwt_secret == _DEV_ONLY_SECRET or len(self.jwt_secret) < 32:
            problems.append("ORA_JWT_SECRET must be a strong, non-default value (>=32 chars).")
        if any("localhost" in origin for origin in self.cors_allowed_origins):
            problems.append("ORA_CORS_ALLOWED_ORIGINS must not include localhost in production.")
        if self.database_url.startswith("sqlite"):
            problems.append("SQLite is not permitted in production; use PostgreSQL.")
        if self.ai_interview_enabled:
            if self.ai_interview_agent_mode == "fake":
                problems.append("ORA_AI_INTERVIEW_AGENT_MODE=fake is not allowed in production.")
            if not self.ai_interview_webhook_secret or len(self.ai_interview_webhook_secret) < 32:
                problems.append(
                    "ORA_AI_INTERVIEW_WEBHOOK_SECRET must be set (>=32 chars) when the "
                    "AI interview is enabled."
                )
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
