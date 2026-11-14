"""Conversation mechanics: when to speak, when to listen, and what to do when people overlap.

`InterviewOrchestrator` decides WHAT to say (fixed approved questions, in order). This module
decides WHEN, and repairs the situations that break real phone-style conversations:

1. Listening - the agent speaks, then waits. A turn is only handed to the orchestrator once
   Pipecat's end-of-turn detection says the candidate has finished (voice activity + a
   turn-detection model), not after a fixed quiet gap, so a thinking pause does not cut an
   answer in half.
2. Candidate keeps talking - if more words arrive while a turn is being processed, the turn is
   undone and merged with the new words (`OrchestratorSnapshot.restore`) so the answer is
   handled once, whole.
3. Candidate talks over the agent's reply almost at once - the new words are the rest of the
   previous answer, not a reply to a question they never heard. The earlier turn is undone and
   merged.
4. Candidate cuts the agent off during a question - a bare "okay" or "sorry?" is not an answer.
   If the question was not fully heard it is asked again; "um"/"hmm" are never answers.
5. Silence - one gentle prompt, then the interview ends with a recorded reason (unchanged
   behaviour from the first version), and a hard time limit.

All of it runs on one asyncio lock, so decisions are serialised and a question is never
recorded as asked unless the candidate was actually given it.

Privacy: this module never puts speech on a span or in a log line; only counts and timings.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from opentelemetry.trace import SpanContext

from ..config import Settings
from ..models import EndReason
from ..observability import interview_metrics, interview_span, set_safe_attributes
from ..orchestrator import InterviewOrchestrator, InterviewState, OrchestratorSnapshot

log = logging.getLogger(__name__)

SPEECH_WORDS_PER_SECOND = 2.6  # typical TTS rate; used to estimate how long a line takes
SPEECH_LATENCY_ALLOWANCE = 0.4
HEARD_FRACTION = 0.8  # this much of a line played counts as "the candidate heard it"
_MAX_FILLER_WORDS = 3

# Sounds a person makes while thinking. Never an answer.
_THINKING = frozenset({"um", "umm", "uh", "uhh", "hmm", "hm", "mm", "mmm", "mhm", "ah", "oh", "huh", "er", "well", "so"})
# Acknowledgements and "pardon?" - not an answer when they come as the agent is speaking or was
# cut off, but a real answer to a yes/no question otherwise ("yes").
_ACKNOWLEDGEMENT = frozenset(
    {"yes", "yeah", "yep", "yup", "ok", "okay", "right", "sure", "alright", "sorry", "hello", "hi",
     "what", "again", "repeat", "please", "pardon", "excuse", "me", "go", "ahead"}
)

# speak(lines, interrupt=...) queues the lines for the voice; interrupt=True first cuts off
# whatever the agent is still saying (used for typed answers, which arrive without a voice
# interruption).
SpeakFn = Callable[..., Awaitable[None]]
NotifyFn = Callable[[dict[str, Any]], Awaitable[None]]
FinishFn = Callable[[bool], Awaitable[None]]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def is_thinking_filler(text: str) -> bool:
    tokens = _tokens(text)
    return 0 < len(tokens) <= _MAX_FILLER_WORDS and all(t in _THINKING for t in tokens)


def is_acknowledgement(text: str) -> bool:
    tokens = _tokens(text)
    return 0 < len(tokens) <= _MAX_FILLER_WORDS and all(
        t in _ACKNOWLEDGEMENT or t in _THINKING for t in tokens
    )


@dataclass
class _Speech:
    """What the agent most recently said, and what has happened to it since."""

    called_at: float
    est_seconds: float
    from_turn: bool  # produced as the reply to a candidate turn (not a re-ask or idle prompt)
    awaiting_answer: bool  # the interview is still running, so the candidate is expected to reply
    playback_started_at: float | None = None
    interrupted_at: float | None = None
    heard_fraction: float = 0.0
    finished: bool = False
    # Each line is one speech context. A "bot stopped" signal between two lines (while the next
    # one is still being synthesised) must not count as the agent being done.
    lines: int = 1
    lines_synthesised: int = 0


@dataclass
class _Commit:
    """The last candidate turn handed to the orchestrator, kept so it can be undone."""

    snapshot: OrchestratorSnapshot
    text: str


class FlowController:
    def __init__(
        self,
        *,
        orchestrator: InterviewOrchestrator,
        settings: Settings,
        interview_id: str,
        speak: SpeakFn,
        notify: NotifyFn,
        finish: FinishFn,
        clock: Callable[[], float] = time.monotonic,
        turn_context: Callable[[], SpanContext | None] = lambda: None,
        run_blocking: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    ) -> None:
        self._orch = orchestrator
        self._settings = settings
        self._interview_id = interview_id
        self._speak = speak
        self._notify = notify
        self._finish = finish
        self._clock = clock
        self._turn_context = turn_context
        self._run_blocking = run_blocking
        self._metrics = interview_metrics()

        self._lock = asyncio.Lock()
        self._speech: _Speech | None = None
        self._last_commit: _Commit | None = None
        self._carry = ""
        self._last_words_at = float("-inf")
        self._last_activity = clock()
        self._ended = False
        self._closing_pending = False
        self._end_sent = False
        self._carry_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ properties

    @property
    def ended(self) -> bool:
        return self._ended

    def _agent_active(self) -> bool:
        sp = self._speech
        if sp is None or sp.finished or sp.interrupted_at is not None:
            return False
        # Safety net: if the "bot stopped" signal never arrives (a failed synthesis), stop
        # treating the agent as talking after the expected length plus a margin.
        return self._clock() - sp.called_at < sp.est_seconds + 15

    # ------------------------------------------------------------ pipeline events

    async def start(self) -> None:
        async with self._lock:
            if self._ended:
                return
            await self._say(self._orch.opening(), from_turn=False)

    def on_words_heard(self) -> None:
        """Any interim or final transcript text arrived (the candidate is talking)."""
        self._last_words_at = self._clock()
        self._last_activity = self._last_words_at

    def on_bot_started(self) -> None:
        sp = self._speech
        if sp is not None and sp.playback_started_at is None and sp.interrupted_at is None:
            sp.playback_started_at = self._clock()

    def on_tts_line_synthesised(self) -> None:
        """Text-to-speech finished producing one line of the current speech."""
        sp = self._speech
        if sp is not None and sp.interrupted_at is None:
            sp.lines_synthesised += 1

    async def on_bot_stopped(self) -> None:
        now = self._clock()
        self._last_activity = now
        sp = self._speech
        if sp is None or sp.finished or sp.interrupted_at is not None:
            return
        # The output goes quiet briefly between two lines while the next is synthesised. Only
        # when every line has been produced does "stopped" mean the agent is done talking.
        if sp.playback_started_at is not None and sp.lines_synthesised >= sp.lines:
            sp.finished = True
            await self._notify({"type": "agent_audio_end"})
            if self._closing_pending:
                await self._send_end(graceful=True)

    def on_interrupted(self) -> None:
        sp = self._speech
        if sp is None or sp.finished or sp.interrupted_at is not None:
            return
        now = self._clock()
        sp.interrupted_at = now
        played = 0.0 if sp.playback_started_at is None else now - sp.playback_started_at
        sp.heard_fraction = min(1.0, played / sp.est_seconds) if sp.est_seconds > 0 else 1.0
        self._metrics.interruptions.add(1)

    # ------------------------------------------------------------ candidate turns

    async def on_user_turn(self, text: str, *, typed: bool = False) -> None:
        """A finished candidate turn (end-of-turn detected) or a typed answer."""
        async with self._lock:
            if self._ended or self._orch.state is not InterviewState.ASKING:
                return
            text = f"{self._carry} {text}".strip()
            self._carry = ""
            if not text:
                return
            self._last_activity = self._clock()

            if not typed:
                handled, text = await self._repair(text)
                if handled:
                    return
            await self._commit(text, allow_defer=not typed, interrupt=typed)

    async def _repair(self, text: str) -> tuple[bool, str]:
        """Apply the overlap rules. Returns (turn fully handled, text to commit otherwise)."""
        sp = self._speech
        window = self._settings.answer_continuation_window_secs

        # Rule 3: they talked over our reply almost immediately -> the rest of their answer.
        if (
            sp is not None
            and sp.interrupted_at is not None
            and sp.from_turn
            and sp.interrupted_at - sp.called_at <= window
            and self._last_commit is not None
            and not is_acknowledgement(text)
        ):
            self._orch.restore(self._last_commit.snapshot)
            merged = f"{self._last_commit.text} {text}"
            self._last_commit = None
            self._metrics.turns_merged.add(1)
            return False, merged

        # Rule 4a: thinking noises are never answers.
        if is_thinking_filler(text):
            self._metrics.fillers_ignored.add(1)
            return True, text

        # Rule 4b: cut off during a question and only acknowledged -> ask it again.
        if (
            sp is not None
            and sp.interrupted_at is not None
            and sp.awaiting_answer
            and sp.heard_fraction < HEARD_FRACTION
            and is_acknowledgement(text)
        ):
            self._metrics.reasks.add(1)
            await self._say(self._orch.repeat_current_question(), from_turn=False)
            return True, text

        # Rule 4c: a bare acknowledgement while the agent talks (or right after) is not an answer.
        if is_acknowledgement(text) and (
            self._agent_active() or (sp is not None and sp.interrupted_at is not None)
        ):
            self._metrics.fillers_ignored.add(1)
            return True, text

        return False, text

    async def _commit(self, text: str, *, allow_defer: bool, interrupt: bool = False) -> None:
        orch = self._orch
        before = orch.snapshot()
        began = self._clock()
        asked_before = len(orch.asked_question_ids)
        skipped_before = len(orch.skipped_question_ids)

        with interview_span(
            "interview.turn",
            interview_id=self._interview_id,
            parent=self._turn_context(),
            attributes={
                "interview.question_index": max(asked_before - 1, 0),
                "interview.answer_words": len(text.split()),
                "interview.typed": interrupt,
            },
        ) as span:
            lines: list[str] = await self._run_blocking(orch.handle_candidate_utterance, text)

            if allow_defer and self._last_words_at > began and orch.state is not InterviewState.ENDED:
                # The candidate started talking again while we were deciding: undo and merge.
                orch.restore(before)
                self._carry = text
                self._schedule_carry_flush()
                self._metrics.turns_merged.add(1)
                set_safe_attributes(span, {"interview.action": "deferred"})
                return

            self._last_commit = _Commit(snapshot=before, text=text)
            self._metrics.turns.add(1)
            set_safe_attributes(
                span,
                {
                    "interview.action": self._action(
                        asked_before, skipped_before, len(lines)
                    ),
                    "interview.reply_lines": len(lines),
                },
            )
            await self._say(lines, from_turn=True, interrupt=interrupt)

    def _action(self, asked_before: int, skipped_before: int, lines: int) -> str:
        orch = self._orch
        if orch.state is InterviewState.ENDED:
            return f"ended_{orch.end_reason}"
        if len(orch.skipped_question_ids) > skipped_before:
            return "skipped"
        if len(orch.asked_question_ids) > asked_before:
            return "advanced"
        return "followup_or_repeat" if lines else "no_reply"

    def _schedule_carry_flush(self) -> None:
        task = asyncio.get_running_loop().create_task(self._flush_carry())
        self._carry_tasks.add(task)
        task.add_done_callback(self._carry_tasks.discard)

    async def _flush_carry(self) -> None:
        """If the candidate does not follow up, process the deferred words after a short wait."""
        await asyncio.sleep(self._settings.turn_max_pause_secs + 1.0)
        async with self._lock:
            if not self._carry or self._ended or self._orch.state is not InterviewState.ASKING:
                return
            text, self._carry = self._carry, ""
            await self._commit(text, allow_defer=False)

    # ------------------------------------------------------------ time-based events

    async def tick(self) -> None:
        """Called about once a second: time limit, silence, and a stuck closing line."""
        if self._closing_pending and not self._agent_active():
            await self._send_end(graceful=True)  # the "finished speaking" signal never came
            return
        if self._ended or self._lock.locked():
            return
        async with self._lock:
            orch = self._orch
            if self._ended or orch.state is not InterviewState.ASKING:
                return
            if orch.elapsed_seconds >= self._settings.max_interview_seconds:
                await self._say(orch.on_time_limit(), from_turn=False)
                return
            quiet_for = self._clock() - self._last_activity
            if (
                quiet_for >= self._settings.idle_prompt_seconds
                and not self._agent_active()
                and not self._carry
            ):
                self._last_activity = self._clock()
                self._metrics.idle_prompts.add(1)
                await self._say(orch.on_idle(), from_turn=False)

    # ------------------------------------------------------------ ending

    async def on_client_end(self) -> None:
        """The candidate pressed End: stop immediately, no closing speech."""
        async with self._lock:
            if self._ended:
                return
            self._orch.mark_ended(EndReason.CANDIDATE_REQUESTED_STOP)
            await self._conclude(graceful=False)

    async def on_disconnect(self) -> None:
        async with self._lock:
            if self._ended:
                return
            self._orch.mark_ended(EndReason.CANDIDATE_DISCONNECTED)
            self._ended = True
            self._record_end()

    async def on_error(self) -> None:
        async with self._lock:
            if self._ended:
                return
            self._orch.mark_ended(EndReason.ERROR)
            await self._conclude(graceful=False)

    async def close(self) -> None:
        for task in list(self._carry_tasks):
            task.cancel()
        for task in list(self._carry_tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # ------------------------------------------------------------ internals

    async def _say(self, lines: list[str], *, from_turn: bool, interrupt: bool = False) -> None:
        orch = self._orch
        if lines:
            words = sum(len(line.split()) for line in lines)
            self._speech = _Speech(
                called_at=self._clock(),
                est_seconds=words / SPEECH_WORDS_PER_SECOND + SPEECH_LATENCY_ALLOWANCE,
                from_turn=from_turn,
                awaiting_answer=orch.state is InterviewState.ASKING,
                lines=len(lines),
            )
            self._last_activity = self._clock()
            await self._speak(lines, interrupt=interrupt)
        if orch.state is InterviewState.ENDED:
            # Closing speech (if any) is already queued; the pipeline ends after it plays.
            await self._conclude(graceful=True)

    async def _conclude(self, *, graceful: bool) -> None:
        self._ended = True
        self._record_end()
        if graceful and self._agent_active():
            # Same order as before: the closing line plays, then "ended", then the socket
            # closes. `on_bot_stopped` (or `tick`, if that signal never comes) sends it.
            self._closing_pending = True
            return
        await self._send_end(graceful=graceful)

    async def _send_end(self, *, graceful: bool) -> None:
        if self._end_sent:
            return
        self._end_sent = True
        self._closing_pending = False
        await self._notify({"type": "ended", "reason": str(self._orch.end_reason)})
        await self._finish(graceful)

    def _record_end(self) -> None:
        reason = str(self._orch.end_reason or "unknown")
        self._metrics.ended.add(1, {"reason": reason})
        self._metrics.duration.record(self._orch.elapsed_seconds, {"reason": reason})
