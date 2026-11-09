"""Wiring: builds the concrete adapters from settings. Core modules never import AWS directly."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field
from uuid import UUID

from .config import Settings
from .llm import BedrockGptOssModel, ScriptedModel
from .models import QuestionSet
from .planner import QuestionPlanner
from .ports import LanguageModel, ResultSink, SpeechToText, TextToSpeech
from .sinks import build_sink
from .speech import FakeSpeechToText, PollyTextToSpeech, SilentTextToSpeech, TranscribeSpeechToText
from .summariser import InterviewSummariser


@dataclass
class Runtime:
    settings: Settings
    llm: LanguageModel
    stt: SpeechToText
    tts: TextToSpeech
    sink: ResultSink
    planner: QuestionPlanner
    summariser: InterviewSummariser
    registry: PreparedInterviews = field(default_factory=lambda: PreparedInterviews())


def build_runtime(settings: Settings) -> Runtime:
    if settings.adapters == "aws":
        llm: LanguageModel = BedrockGptOssModel(settings)
        stt: SpeechToText = TranscribeSpeechToText(settings)
        tts: TextToSpeech = PollyTextToSpeech(settings)
    else:
        llm, stt, tts = ScriptedModel(), FakeSpeechToText(), SilentTextToSpeech()
    return Runtime(
        settings=settings,
        llm=llm,
        stt=stt,
        tts=tts,
        sink=build_sink(settings),
        planner=QuestionPlanner(llm, settings),
        summariser=InterviewSummariser(llm, settings),
    )


@dataclass(frozen=True)
class PreparedInterview:
    question_set: QuestionSet
    role_title: str
    join_token: str
    created_at: float


class PreparedInterviews:
    """Per-process store of interviews prepared by the HR platform.

    An AgentCore runtime session maps to one isolated microVM, so `prepare_session` and the later
    WebSocket connection must use the same runtime session id to reach this same process.
    Entries are single use and expire.
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._items: dict[UUID, PreparedInterview] = {}
        self._ttl = ttl_seconds

    def put(self, interview_id: UUID, question_set: QuestionSet, role_title: str) -> str:
        self._evict()
        token = secrets.token_urlsafe(24)
        self._items[interview_id] = PreparedInterview(
            question_set, role_title, token, time.monotonic()
        )
        return token

    def take(self, interview_id: UUID, token: str) -> PreparedInterview | None:
        """Constant-time token check. A wrong token does not consume the entry."""
        self._evict()
        item = self._items.get(interview_id)
        if item is None or not hmac.compare_digest(item.join_token, token):
            return None
        del self._items[interview_id]
        return item

    def _evict(self) -> None:
        cutoff = time.monotonic() - self._ttl
        for key in [k for k, v in self._items.items() if v.created_at < cutoff]:
            del self._items[key]
