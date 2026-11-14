"""Pipecat processors that connect the conversation rules (`flow.FlowController`) to the
pipeline. They only translate frames; the decisions live in `flow.py`.

Pipeline order:

    transport.input -> stt -> TranscriptTap -> user aggregator (VAD + end-of-turn)
        -> InterviewFlowProcessor -> tts -> transport.output
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from opentelemetry.trace import SpanContext
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    EndWorkerFrame,
    Frame,
    InputTransportMessageFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..config import Settings
from ..orchestrator import InterviewOrchestrator
from .flow import FlowController

log = logging.getLogger(__name__)

_MAX_TYPED_CHARS = 3000
_TICK_SECONDS = 1.0


class TranscriptTap(FrameProcessor):
    """Shows the candidate their own words live and tells the controller they are talking.

    Sits between speech-to-text and the turn aggregator so it sees every interim result.
    """

    def __init__(self, controller_getter: Any) -> None:
        super().__init__()
        self._controller = controller_getter

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if (
            isinstance(frame, (InterimTranscriptionFrame, TranscriptionFrame))
            and frame.text.strip()
            and not self._controller().ended
        ):
            self._controller().on_words_heard()
            await self.push_frame(
                OutputTransportMessageUrgentFrame(
                    message={
                        "type": "transcript",
                        "role": "candidate",
                        "text": frame.text,
                        "final": isinstance(frame, TranscriptionFrame),
                    }
                )
            )
        await self.push_frame(frame, direction)


class SpeechProgressTap(FrameProcessor):
    """Sits after text-to-speech and reports each line the voice has finished producing."""

    def __init__(self, controller_getter: Any) -> None:
        super().__init__()
        self._controller = controller_getter

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            self._controller().on_tts_line_synthesised()
        await self.push_frame(frame, direction)


class InterviewFlowProcessor(FrameProcessor):
    def __init__(
        self,
        *,
        orchestrator: InterviewOrchestrator,
        settings: Settings,
        interview_id: str,
        turn_context: Any = lambda: None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._orch = orchestrator
        self._tick_task: asyncio.Task[None] | None = None
        self.controller = FlowController(
            orchestrator=orchestrator,
            settings=settings,
            interview_id=interview_id,
            speak=self._speak,
            notify=self._notify,
            finish=self._finish,
            turn_context=turn_context,
        )

    def set_turn_context(self, getter: Any) -> None:
        self.controller._turn_context = getter

    # ------------------------------------------------------------ controller -> pipeline

    async def _speak(self, lines: list[str], *, interrupt: bool = False) -> None:
        if interrupt:
            await self.push_frame(InterruptionFrame())
        for line in lines:
            question = self._orch.current_question
            await self.push_frame(
                OutputTransportMessageUrgentFrame(
                    message={
                        "type": "agent_text",
                        "text": line,
                        "question_id": question.id if question else None,
                    }
                )
            )
            await self.push_frame(TTSSpeakFrame(line, append_to_context=False))

    async def _notify(self, payload: dict[str, Any]) -> None:
        await self.push_frame(OutputTransportMessageUrgentFrame(message=payload))

    async def _finish(self, graceful: bool) -> None:
        if not graceful:
            await self.push_frame(InterruptionFrame())  # stop speaking now
        # Pushed downstream it follows any queued speech (so a closing line plays), then the
        # worker ends the whole pipeline, including the transport, which closes the socket.
        await self.push_frame(EndWorkerFrame(reason="interview_ended"))

    # ------------------------------------------------------------ pipeline -> controller

    def submit_turn(self, text: str) -> None:
        """A finished candidate turn from the aggregator."""
        self.create_task(self.controller.on_user_turn(text), name="interview-turn")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            if self._tick_task is None:
                self._tick_task = self.create_task(self._tick_loop(), name="interview-tick")
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_background()

        if isinstance(frame, InputTransportMessageFrame):
            self._handle_client_message(frame.message)
            return  # client control messages stop here

        if isinstance(frame, LLMContextFrame):
            return  # the aggregator's "run the LLM" signal; there is no LLM in this pipeline

        if isinstance(frame, BotStartedSpeakingFrame):
            self.controller.on_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self.controller.on_bot_stopped()
        elif isinstance(frame, InterruptionFrame):
            self.controller.on_interrupted()

        await self.push_frame(frame, direction)

    def _handle_client_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if self.controller.ended:
            return  # nothing is accepted once the interview has ended
        if kind == "utterance":
            text = message.get("text")
            if self._settings.allow_text_input and isinstance(text, str) and text.strip():
                self.create_task(self._typed(text[:_MAX_TYPED_CHARS].strip()), name="typed-turn")
        elif kind == "end":
            self.create_task(self.controller.on_client_end(), name="client-end")

    async def _typed(self, text: str) -> None:
        # Show typed words in the transcript like spoken ones, then handle them as a turn.
        self.controller.on_words_heard()
        await self.push_frame(
            OutputTransportMessageUrgentFrame(
                message={"type": "transcript", "role": "candidate", "text": text, "final": True}
            )
        )
        await self.controller.on_user_turn(text, typed=True)

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            try:
                await self.controller.tick()
            except Exception as exc:  # noqa: BLE001 - a tick failure must not end the interview
                log.error("tick_failed", extra={"error": type(exc).__name__})

    async def cleanup(self) -> None:
        await self._stop_background()
        await super().cleanup()  # type: ignore[no-untyped-call]

    async def _stop_background(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tick_task
            self._tick_task = None
        await self.controller.close()


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def span_context_getter(worker: Any) -> Any:
    """Return a callable giving the current Pipecat turn's span context (or None)."""

    def _get() -> SpanContext | None:
        observer = getattr(worker, "turn_trace_observer", None)
        if observer is None:
            return None
        try:
            return observer.get_current_turn_context()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001 - tracing must never affect the interview
            return None

    return _get
