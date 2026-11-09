"""Real-time voice session: audio in -> STT -> orchestrator -> TTS -> audio out.

One VoiceSession handles one interview over one Transport. It owns turn-taking: it waits for a
short quiet period after the candidate's last final transcript before replying, stops speaking when
the candidate talks over the agent (barge-in), and prompts or ends on silence or time limit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable

from .config import Settings
from .models import EndReason, InterviewRecord
from .orchestrator import InterviewOrchestrator, InterviewState
from .ports import ResultSink, SpeechToText, TextToSpeech, Transport
from .summariser import InterviewSummariser

log = logging.getLogger(__name__)

_BARGE_IN_MIN_WORDS = 3  # avoids reacting to coughs, echo fragments and "mm"
_AUDIO_QUEUE_MAX = 300  # about 30 s of 100 ms chunks; older audio is dropped if STT stalls


class VoiceSession:
    def __init__(
        self,
        *,
        orchestrator: InterviewOrchestrator,
        summariser: InterviewSummariser,
        stt: SpeechToText,
        tts: TextToSpeech,
        transport: Transport,
        sink: ResultSink,
        settings: Settings,
    ) -> None:
        self._orch = orchestrator
        self._summariser = summariser
        self._stt = stt
        self._tts = tts
        self._transport = transport
        self._sink = sink
        self._settings = settings
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=_AUDIO_QUEUE_MAX)
        self._finals: list[str] = []
        self._debounce: asyncio.Task[None] | None = None
        self._turn: asyncio.Task[None] | None = None
        self._speaking = False
        self._done = asyncio.Event()
        self._last_activity = time.monotonic()
        self._id = str(orchestrator.interview_id)

    # ------------------------------------------------------------ lifecycle

    async def run(self) -> InterviewRecord:
        await self._launch(self._orch.opening)
        workers = [
            asyncio.create_task(self._receive_loop()),
            asyncio.create_task(self._stt_loop()),
            asyncio.create_task(self._watchdog()),
        ]
        try:
            await self._done.wait()
            # Let the closing line finish playing unless the candidate already left.
            if (
                self._turn
                and not self._turn.done()
                and self._orch.end_reason
                not in (
                    EndReason.CANDIDATE_DISCONNECTED,
                    EndReason.ERROR,
                )
            ):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(self._turn), timeout=30)
        finally:
            # End the audio stream first so speech-to-text closes cleanly instead of being
            # cancelled mid-read (the Transcribe SDK logs a spurious traceback when cancelled).
            stt_task = workers[1]
            with contextlib.suppress(asyncio.QueueEmpty):
                while self._audio_queue.full():
                    self._audio_queue.get_nowait()
            self._audio_queue.put_nowait(None)
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(stt_task), timeout=3)
            for task in (*workers, self._debounce, self._turn):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(t for t in (*workers, self._debounce, self._turn) if t),
                return_exceptions=True,
            )

        await self._safe_send({"type": "ended", "reason": str(self._orch.end_reason)})
        summary = await asyncio.to_thread(self._summariser.summarise, self._orch)
        record = InterviewRecord(summary=summary, transcript=self._orch.turns)
        location = await asyncio.to_thread(self._sink.persist, record)
        log.info("interview_persisted", extra={"interview_id": self._id, "location": location})
        return record

    # ------------------------------------------------------------ inbound

    async def _receive_loop(self) -> None:
        while True:
            message = await self._transport.receive()
            kind = message["type"]
            if kind == "audio":
                if self._audio_queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(message["data"])
            elif kind == "json":
                await self._on_client_message(message["data"])
            elif kind == "disconnect":
                self._orch.mark_ended(EndReason.CANDIDATE_DISCONNECTED)
                self._done.set()
                return

    async def _on_client_message(self, data: dict[str, object]) -> None:
        msg_type = data.get("type")
        if msg_type == "utterance":
            text = data.get("text")
            if self._settings.allow_text_input and isinstance(text, str) and text.strip():
                await self._on_transcript(text[:3000], final=True, typed=True)
        elif msg_type == "end":
            await self._interrupt()  # the End button stops speech immediately
            self._orch.mark_ended(EndReason.CANDIDATE_REQUESTED_STOP)
            self._done.set()

    async def _audio_iter(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                return
            yield chunk

    async def _stt_loop(self) -> None:
        try:
            async for event in self._stt.stream(self._audio_iter()):
                await self._on_transcript(event.text, final=event.is_final, typed=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - degrade to typed input rather than end the call
            log.error("stt_failed", extra={"interview_id": self._id, "error": type(exc).__name__})
            await self._safe_send(
                {
                    "type": "warning",
                    "code": "speech_recognition_unavailable",
                    "text_input": self._settings.allow_text_input,
                }
            )
            if not self._settings.allow_text_input:
                self._orch.mark_ended(EndReason.ERROR)
                self._done.set()

    async def _on_transcript(self, text: str, *, final: bool, typed: bool) -> None:
        text = text.strip()
        if not text or self._orch.state is not InterviewState.ASKING:
            return
        self._last_activity = time.monotonic()
        await self._safe_send(
            {"type": "transcript", "role": "candidate", "text": text, "final": final}
        )
        if self._debounce and not self._debounce.done():
            self._debounce.cancel()  # candidate is still speaking
        if not final:
            if self._speaking and len(text.split()) >= _BARGE_IN_MIN_WORDS:
                await self._interrupt()
            return
        self._finals.append(text)
        if typed:
            await self._flush()
        else:
            self._debounce = asyncio.create_task(self._flush_after_silence())

    async def _flush_after_silence(self) -> None:
        await asyncio.sleep(self._settings.endpoint_silence_ms / 1000)
        await self._flush()

    async def _flush(self) -> None:
        if not self._finals:
            return
        utterance = " ".join(self._finals)
        self._finals.clear()
        await self._launch(lambda: self._orch.handle_candidate_utterance(utterance))

    # ------------------------------------------------------------ outbound

    async def _launch(self, producer: Callable[[], list[str]]) -> None:
        if self._orch.state is InterviewState.ENDED:
            return
        await self._interrupt()
        self._turn = asyncio.create_task(self._run_turn(producer))

    async def _run_turn(self, producer: Callable[[], list[str]]) -> None:
        lines = await asyncio.to_thread(producer)  # may call the LLM, so keep off the event loop
        if lines:
            await self._speak(lines)
        if self._orch.state is InterviewState.ENDED:
            self._done.set()

    async def _speak(self, lines: list[str]) -> None:
        self._speaking = True
        try:
            for line in lines:
                question = self._orch.current_question
                await self._safe_send(
                    {
                        "type": "agent_text",
                        "text": line,
                        "question_id": question.id if question else None,
                    }
                )
                try:
                    async for chunk in self._tts.synthesize(line):
                        await self._transport.send_bytes(chunk)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - text was already sent; keep interview alive
                    log.error(
                        "tts_failed", extra={"interview_id": self._id, "error": type(exc).__name__}
                    )
                    await self._safe_send(
                        {"type": "warning", "code": "speech_synthesis_unavailable"}
                    )
            await self._safe_send({"type": "agent_audio_end"})
        finally:
            self._speaking = False
            self._last_activity = time.monotonic()

    async def _interrupt(self) -> None:
        """Stop the agent's current turn (barge-in or a newer turn replacing it)."""
        if self._orch.state is InterviewState.ENDED:
            return  # never cut off the closing line
        turn = self._turn
        if turn and not turn.done() and turn is not asyncio.current_task():
            was_speaking = self._speaking
            turn.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await turn
            if was_speaking:
                await self._safe_send({"type": "clear"})

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self._orch.state is not InterviewState.ASKING:
                continue
            if self._orch.elapsed_seconds >= self._settings.max_interview_seconds:
                await self._launch(self._orch.on_time_limit)
                continue
            busy = self._speaking or bool(self._finals) or (self._turn and not self._turn.done())
            idle_for = time.monotonic() - self._last_activity
            if not busy and idle_for >= self._settings.idle_prompt_seconds:
                self._last_activity = time.monotonic()
                await self._launch(self._orch.on_idle)

    async def _safe_send(self, payload: dict[str, object]) -> None:
        try:
            await self._transport.send_json(payload)
        except Exception:  # noqa: BLE001 - client may be gone; the interview data is still saved
            log.debug("send_failed", extra={"interview_id": self._id})
