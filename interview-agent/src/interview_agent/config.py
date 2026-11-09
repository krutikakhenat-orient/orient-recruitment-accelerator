"""Environment-based configuration, validated at startup."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INTERVIEW_AGENT_", extra="ignore")

    environment: Literal["local", "dev", "prod"] = "local"
    # "aws" uses Transcribe/Bedrock/Polly. "fake" is for local development only.
    adapters: Literal["aws", "fake"] = "aws"

    aws_region: str = "ap-south-1"

    # --- LLM (gpt-oss-120b on Bedrock, bedrock-runtime Converse) ---
    llm_model_id: str = "openai.gpt-oss-120b-1:0"
    llm_reasoning_effort: Literal["low", "medium", "high"] = "low"
    llm_turn_max_tokens: int = 400  # includes reasoning tokens; the spoken reply stays short
    llm_batch_max_tokens: int = 4000  # planner / summariser
    llm_read_timeout_seconds: int = 20

    # --- Speech ---
    transcribe_language: str = "en-IN"
    sample_rate_hz: int = 16000
    polly_voice_id: str = "Kajal"
    polly_language_code: str = "en-IN"
    polly_engine: Literal["standard", "neural", "generative"] = "neural"
    # Polly can run in a different region from Bedrock/Transcribe (generative voices are not in
    # every region). Defaults to aws_region. Note: a different region means audio text leaves it.
    polly_region: str | None = None

    # --- Interview behaviour ---
    max_interview_seconds: int = 1800
    max_questions: int = 8
    max_followups_per_question: int = 1
    min_words_before_no_followup: int = 25
    # Quiet time after the last final transcript before the agent replies.
    endpoint_silence_ms: int = 800
    idle_prompt_seconds: int = 45
    allow_text_input: bool = True  # typed answers: accessibility fallback and test aid

    # --- Result delivery ---
    output_dir: str = "./out"
    s3_bucket: str | None = None
    s3_prefix: str = "interviews/"
    webhook_url: str | None = None
    webhook_secret: SecretStr | None = None

    @model_validator(mode="after")
    def _validate_environment(self) -> Settings:
        if self.environment == "prod":
            if self.adapters != "aws":
                raise ValueError("fake adapters are not allowed when environment=prod")
            if not (self.s3_bucket or self.webhook_url):
                raise ValueError("prod requires s3_bucket and/or webhook_url to persist results")
        if self.webhook_url and not self.webhook_secret:
            raise ValueError("webhook_url requires webhook_secret")
        if (
            self.webhook_url
            and not self.webhook_url.startswith("https://")
            and (self.environment != "local")
        ):
            raise ValueError("webhook_url must be https outside local")
        return self


@lru_cache
def get_settings() -> Settings:
    # A local .env (git-ignored) is loaded into the process environment so both these settings
    # and boto3 (AWS_PROFILE, AWS_DEFAULT_REGION) see it. Real environment variables win.
    # In AgentCore there is no .env file; settings come from runtime environment variables.
    from dotenv import load_dotenv

    load_dotenv(".env", override=False)
    return Settings()
