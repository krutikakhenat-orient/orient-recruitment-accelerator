"""gpt-oss-120b on Amazon Bedrock (bedrock-runtime Converse API) plus a scripted fake."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from typing import Any

from .config import Settings

log = logging.getLogger(__name__)

_REASONING_TAGS = re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL | re.IGNORECASE)


class LanguageModelError(RuntimeError):
    pass


class BedrockGptOssModel:
    """Thin Converse wrapper. Reasoning content blocks are discarded, only answer text is used."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model_id = settings.llm_model_id
        self._effort = settings.llm_reasoning_effort
        self._send_effort = True
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "bedrock-runtime",
                region_name=settings.aws_region,
                config=Config(
                    retries={"max_attempts": 2, "mode": "standard"},
                    connect_timeout=3,
                    read_timeout=settings.llm_read_timeout_seconds,
                ),
            )
        self._client = client

    def _kwargs(
        self, system: str, user: str, max_tokens: int, temperature: float
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        if self._send_effort:
            kwargs["additionalModelRequestFields"] = {"reasoning_effort": self._effort}
        return kwargs

    def _call(self, fn_name: str, **kwargs: Any) -> Any:
        try:
            return getattr(self._client, fn_name)(**kwargs)
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            # Some regions/endpoints reject the reasoning field; retry once without it.
            if self._send_effort and "reasoning" in str(exc).lower():
                log.warning("llm_reasoning_effort_rejected_retrying_without")
                self._send_effort = False
                kwargs.pop("additionalModelRequestFields", None)
                try:
                    return getattr(self._client, fn_name)(**kwargs)
                except Exception as exc2:  # noqa: BLE001
                    raise LanguageModelError(type(exc2).__name__) from exc2
            raise LanguageModelError(type(exc).__name__) from exc

    def complete(self, *, system: str, user: str, max_tokens: int, temperature: float = 0.2) -> str:
        resp = self._call("converse", **self._kwargs(system, user, max_tokens, temperature))
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b["text"] for b in blocks if "text" in b)
        return _REASONING_TAGS.sub("", text).strip()

    def stream(
        self, *, system: str, user: str, max_tokens: int, temperature: float = 0.4
    ) -> Iterator[str]:
        resp = self._call("converse_stream", **self._kwargs(system, user, max_tokens, temperature))
        for event in resp["stream"]:
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            if "text" in delta:  # "reasoningContent" deltas are intentionally skipped
                yield delta["text"]


class ScriptedModel:
    """Deterministic stand-in for local runs and tests. `responder(system, user)` returns text."""

    model_id = "scripted-fake"

    def __init__(self, responder: Callable[[str, str], str] | None = None) -> None:
        self._responder = responder or (lambda _s, _u: "Could you give a specific example?")
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, max_tokens: int, temperature: float = 0.2) -> str:
        self.calls.append((system, user))
        return self._responder(system, user)

    def stream(
        self, *, system: str, user: str, max_tokens: int, temperature: float = 0.4
    ) -> Iterator[str]:
        self.calls.append((system, user))
        text = self._responder(system, user)
        for i in range(0, len(text), 12):
            yield text[i : i + 12]
