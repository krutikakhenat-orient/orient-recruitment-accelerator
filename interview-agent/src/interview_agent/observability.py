"""OpenTelemetry setup and the few spans the agent adds on top of Pipecat's own.

What is traced
--------------
Pipecat (`enable_tracing`) records one trace per interview: a `conversation` span, a `turn` span
per exchange, and `stt` / `tts` spans with latency metrics. This module adds:

* `interview.question` spans: which question was asked, how many follow-ups, skipped or not.
* `gen_ai` spans around the single optional LLM call (the follow-up wording), using the
  OpenTelemetry GenAI semantic-convention attribute names so CloudWatch generative-AI
  observability can recognise them.

Privacy rule (steering: privacy.md, security.md): spans and logs NEVER carry what the candidate
or the agent said, the candidate's name, or any score. They carry timings, counts and opaque ids.
Pipecat's own STT tracing decorator records the transcript as a span attribute, so the
Transcribe service used here replaces it (see `voice/services.py`); Pipecat's log lines can
contain transcripts, so they are silenced below WARNING.

Where traces go
---------------
* On AgentCore Runtime with `instrumentation.enableOtel = true`, the AWS Distro for
  OpenTelemetry (ADOT) installs the tracer provider and exports to CloudWatch (Transaction
  Search -> GenAI observability). `otel_exporter="auto"` detects that and adds nothing.
* Anywhere else, `otel_exporter="otlp"` exports to the standard `OTEL_EXPORTER_OTLP_*`
  endpoint (a local collector, Jaeger, or an ADOT collector that forwards to CloudWatch).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.trace import NonRecordingSpan, Span, SpanContext, Status, StatusCode

from .config import Settings

log = logging.getLogger(__name__)

TRACER_NAME = "interview_agent"
GENAI_SYSTEM = "aws.bedrock"

# Attributes that must never reach a span. `set_safe_attributes` drops them even if a caller
# passes one by mistake, so a future change cannot quietly start tracing candidate speech.
_FORBIDDEN_TOKENS = frozenset(
    {"text", "transcript", "answer", "prompt", "completion", "content", "email", "utterance", "message"}
)
_FORBIDDEN_PAIRS = (("candidate", "name"), ("full", "name"), ("first", "name"), ("last", "name"))
# A trailing token like these means the value is a measurement, not the content itself.
_MEASUREMENT_SUFFIXES = frozenset({"count", "chars", "words", "len", "length", "seconds", "ms"})


def _is_forbidden_attribute(key: str) -> bool:
    tokens = key.lower().replace(".", "_").split("_")
    if tokens and tokens[-1] in _MEASUREMENT_SUFFIXES:
        return False
    if any(token in _FORBIDDEN_TOKENS for token in tokens):
        return True
    return any(a in tokens and b in tokens for a, b in _FORBIDDEN_PAIRS)


def configure_logging(settings: Settings) -> None:
    """Silence Pipecat's loguru output below WARNING (it logs transcripts at DEBUG/INFO)."""
    try:
        from loguru import logger as loguru_logger
    except ImportError:  # pragma: no cover - loguru ships with pipecat
        return
    loguru_logger.remove()
    loguru_logger.add(sys.stderr, level=settings.pipecat_log_level, format="{time} {level} {name} {message}")


def init_observability(settings: Settings) -> str:
    """Set up tracing once at process start. Returns how it was set up (for the startup log).

    One of: "disabled", "adot" (a provider already installed, e.g. by ADOT), "otlp", "console",
    "none" (spans are created but not exported).
    """
    configure_logging(settings)
    if not settings.otel_enabled:
        return "disabled"

    existing = trace.get_tracer_provider()
    if existing.__class__.__name__ not in {"ProxyTracerProvider", "NoOpTracerProvider"}:
        # ADOT (opentelemetry-instrument) or another bootstrap already owns the provider.
        # Never replace it: a second provider would split the interview across two exporters.
        return "adot"

    try:
        from pipecat.utils.tracing.setup import setup_tracing
    except ImportError:  # pragma: no cover - pipecat tracing extra missing
        log.warning("otel_unavailable")
        return "disabled"

    exporter: Any = None
    mode = settings.otel_exporter
    if mode == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()  # endpoint/headers come from OTEL_EXPORTER_OTLP_* env vars
    if mode in {"auto", "none"}:
        mode = "none"
    ok = setup_tracing(
        service_name=settings.otel_service_name,
        exporter=exporter,
        console_export=(mode == "console"),
    )
    return mode if ok else "disabled"


def tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME)


class InterviewMetrics:
    """OpenTelemetry counters for what happens inside an interview (no content, no ids).

    They are no-ops unless a MeterProvider is configured (ADOT can export them to CloudWatch
    metrics). Typical alarms: a rising `interview.ended{reason=error|candidate_disconnected}`
    rate, or many `interview.turns_merged` (end-of-turn detection cutting people off).
    """

    def __init__(self) -> None:
        meter = metrics.get_meter(TRACER_NAME)
        self.turns = meter.create_counter("interview.turns", description="Candidate turns handled")
        self.interruptions = meter.create_counter(
            "interview.interruptions", description="Times the candidate cut the agent off"
        )
        self.turns_merged = meter.create_counter(
            "interview.turns_merged",
            description="Answers joined to the previous one because the candidate kept talking",
        )
        self.reasks = meter.create_counter(
            "interview.reasks", description="Questions repeated because they were cut off"
        )
        self.fillers_ignored = meter.create_counter(
            "interview.fillers_ignored", description="Short acknowledgements that were not answers"
        )
        self.idle_prompts = meter.create_counter(
            "interview.idle_prompts", description="'Are you still there?' prompts"
        )
        self.ended = meter.create_counter("interview.ended", description="Interviews ended")
        self.duration = meter.create_histogram(
            "interview.duration", unit="s", description="Interview length"
        )


_metrics: InterviewMetrics | None = None


def interview_metrics() -> InterviewMetrics:
    global _metrics
    if _metrics is None:
        _metrics = InterviewMetrics()
    return _metrics


def set_safe_attributes(span: Span, attributes: dict[str, Any]) -> None:
    """Set span attributes, refusing any whose key could carry candidate or agent speech."""
    for key, value in attributes.items():
        if _is_forbidden_attribute(key):
            log.error("span_attribute_refused", extra={"key": key})
            continue
        if value is not None:
            span.set_attribute(key, value)


def _parent_context(parent: SpanContext | None) -> Any:
    if parent is None or not parent.is_valid:
        return None
    return trace.set_span_in_context(NonRecordingSpan(parent))


@contextmanager
def interview_span(
    name: str,
    *,
    interview_id: str,
    parent: SpanContext | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """A span tagged with the interview id (the same value as Pipecat's `conversation.id`)."""
    with tracer().start_as_current_span(name, context=_parent_context(parent)) as span:
        set_safe_attributes(span, {"conversation.id": interview_id, "session.id": interview_id})
        if attributes:
            set_safe_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            span.record_exception(exc)
            raise


@contextmanager
def llm_span(
    settings: Settings,
    *,
    interview_id: str,
    purpose: str,
    parent: SpanContext | None = None,
) -> Iterator[Span]:
    """A GenAI `chat` span for one model call. No prompt or completion is recorded."""
    with interview_span(
        f"chat {settings.llm_model_id}",
        interview_id=interview_id,
        parent=parent,
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.system": GENAI_SYSTEM,
            "gen_ai.provider.name": GENAI_SYSTEM,
            "gen_ai.request.model": settings.llm_model_id,
            "gen_ai.request.max_tokens": settings.llm_turn_max_tokens,
            "interview.llm_purpose": purpose,
        },
    ) as span:
        yield span
