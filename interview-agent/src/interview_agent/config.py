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
    # Quiet time after the last final transcript before the agent replies (legacy engine only;
    # the Pipecat engine decides the end of a turn with voice activity + a turn-detection model).
    endpoint_silence_ms: int = 800
    idle_prompt_seconds: int = 45
    allow_text_input: bool = True  # typed answers: accessibility fallback and test aid

    # --- Voice engine ---
    # "pipecat": Pipecat pipeline (VAD, smart end-of-turn detection, interruption handling,
    # tracing). "legacy": the original hand-written asyncio session, kept as a rollback switch.
    voice_engine: Literal["pipecat", "legacy"] = "pipecat"
    # Voice activity detection: how long the audio must be quiet before the end-of-turn model is
    # asked whether the candidate has finished.
    vad_stop_secs: float = 0.4
    # The end-of-turn model may judge the answer unfinished (a thinking pause). The turn is
    # still closed after this much silence, so a candidate who stops talking is never stuck.
    turn_max_pause_secs: float = 3.5
    # While the agent is speaking, the candidate must say at least this many words to cut it
    # off. Coughs, "mm", and the agent's own voice picked up by the microphone do not.
    barge_in_min_words: int = 3
    # If the candidate keeps talking within this long of the agent starting its next line, the
    # new words are joined to the previous answer instead of becoming a reply to a question
    # the candidate has not heard yet.
    answer_continuation_window_secs: float = 2.5

    # --- Observability (OpenTelemetry) ---
    # Spans never contain what the candidate or agent said; only timings, counts and ids.
    otel_enabled: bool = True
    otel_service_name: str = "interview-agent"
    # "auto": use the provider the AWS Distro for OpenTelemetry (ADOT) installs on AgentCore;
    # "otlp": export to OTEL_EXPORTER_OTLP_* (a collector or the CloudWatch OTLP endpoint);
    # "console": print spans (debugging); "none": create spans but export nothing.
    otel_exporter: Literal["auto", "otlp", "console", "none"] = "auto"
    # Pipecat's own log lines can contain transcripts. At INFO and below they are dropped.
    pipecat_log_level: Literal["WARNING", "ERROR", "CRITICAL"] = "WARNING"

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
