"""Interfaces (ports) so AWS services can be swapped or faked. Core logic depends only on these."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from .models import InterviewRecord


class LanguageModel(Protocol):
    model_id: str

    def complete(self, *, system: str, user: str, max_tokens: int, temperature: float = 0.2) -> str:
        """Blocking single response."""
        ...

    def stream(
        self, *, system: str, user: str, max_tokens: int, temperature: float = 0.4
    ) -> Iterator[str]:
        """Blocking iterator of text deltas (reasoning tokens are never yielded)."""
        ...


@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    is_final: bool
    confidence: float | None = None


class SpeechToText(Protocol):
    def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        """Consume 16 kHz mono PCM s16le chunks; yield partial and final transcripts."""
        ...


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield 16 kHz mono PCM s16le chunks for one sentence."""
        ...


class ResultSink(Protocol):
    def persist(self, record: InterviewRecord) -> str:
        """Store the record and return a location string. Raise on failure."""
        ...


class Transport(Protocol):
    """Candidate-facing duplex channel (a WebSocket in production)."""

    async def send_json(self, payload: dict[str, Any]) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def receive(self) -> dict[str, Any]:
        """Return {"type": "audio", "data": bytes} | {"type": "json", "data": dict}
        | {"type": "disconnect"}."""
        ...
