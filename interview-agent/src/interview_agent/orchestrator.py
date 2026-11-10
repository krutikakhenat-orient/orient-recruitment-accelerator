"""Interview flow control.

The flow is deterministic: approved questions are asked verbatim and in order. The language model
is used only to phrase one optional follow-up for a thin answer, its output is guarded, and a
failure falls back to a fixed follow-up. The model never decides to end, skip or judge anything.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .config import Settings
from .llm import LanguageModelError
from .models import EndReason, Question, QuestionSet, Speaker, TranscriptTurn
from .ports import LanguageModel
from .prompts import FOLLOWUP_SYSTEM
from .safety import guard_spoken_output, sanitise_untrusted, wrap_untrusted

log = logging.getLogger(__name__)

_STOP = re.compile(
    r"\b(stop|end|quit|finish)\b.{0,25}\b(interview|this|now|here|call)\b"
    r"|\bi\s+(want|wish|would\s+like)\s+to\s+(stop|end|withdraw|leave)\b"
    r"|\bwithdraw\b.{0,20}\bconsent\b",
    re.IGNORECASE,
)
_REPEAT = re.compile(
    r"\b(repeat|say\s+that\s+again|come\s+again|pardon|didn'?t\s+(catch|hear|get)\s+that)\b",
    re.IGNORECASE,
)
_SKIP = re.compile(
    r"\b(skip|pass\s+on\s+this|next\s+question|rather\s+not\s+(answer|say)|"
    r"(don'?t|do\s+not)\s+want\s+to\s+answer|prefer\s+not\s+to\s+(answer|say))\b",
    re.IGNORECASE,
)
_MAX_INTENT_WORDS = 14  # intents only count in short utterances, never inside a long answer

_ACKNOWLEDGEMENTS = ("Thank you.", "Got it.", "Understood.", "Thanks for sharing that.")
_FALLBACK_FOLLOWUP = "Could you share a specific example, and describe your own role in it?"

OPENING_TEMPLATE = (
    "Hello, and thank you for joining. I am an automated interviewer for the {role} role. "
    "This conversation is saved as a transcript for the hiring team, and a person will review it. "
    "You can ask me to repeat a question, skip one, or stop at any time. Let's begin."
)
CLOSING_LINE = (
    "Thank you for your time. That completes the interview. "
    "The hiring team will review your responses."
)
TIME_LIMIT_LINE = (
    "We have reached the time limit for this interview. Thank you for your time. "
    "The hiring team will review your responses."
)
STOP_LINE = "Of course, we will stop here. Thank you for your time."
IDLE_LINE = "Are you still there? Take your time, and let me know if you would like me to repeat the question."
NO_RESPONSE_LINE = (
    "I have not heard a response, so I will end the interview here. Thank you for your time."
)


class InterviewState(StrEnum):
    NOT_STARTED = "not_started"
    ASKING = "asking"
    ENDED = "ended"


@dataclass(frozen=True)
class OrchestratorSnapshot:
    """A copy of everything a turn can change, so a turn can be undone (see `restore`)."""

    state: InterviewState
    end_reason: EndReason | None
    turns: tuple[TranscriptTurn, ...]
    integrity_flags: tuple[str, ...]
    skipped_question_ids: tuple[str, ...]
    asked_question_ids: tuple[str, ...]
    index: int
    followups_used: int
    ack_cursor: int
    idle_prompts: int


class InterviewOrchestrator:
    def __init__(
        self,
        *,
        interview_id: UUID,
        question_set: QuestionSet,
        role_title: str,
        llm: LanguageModel,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
        trace_llm: Callable[[], AbstractContextManager[object]] | None = None,
    ) -> None:
        if not question_set.approved:
            raise ValueError("question_set_not_approved")
        self.interview_id = interview_id
        self.question_set = question_set
        self._role = sanitise_untrusted(role_title, max_chars=120).text or "open"
        self._llm = llm
        self._settings = settings
        self._clock = clock
        # Optional hook that wraps the one LLM call in a tracing span (observability.llm_span).
        self.trace_llm = trace_llm
        self.state = InterviewState.NOT_STARTED
        self.end_reason: EndReason | None = None
        self.turns: list[TranscriptTurn] = []
        self.integrity_flags: list[str] = []
        self.skipped_question_ids: list[str] = []
        self.asked_question_ids: list[str] = []
        self._index = -1
        self._followups_used = 0
        self._ack_cursor = 0
        self._idle_prompts = 0
        self._started_at = self._clock()

    # ------------------------------------------------------------ public API

    @property
    def current_question(self) -> Question | None:
        if 0 <= self._index < len(self.question_set.questions):
            return self.question_set.questions[self._index]
        return None

    @property
    def elapsed_seconds(self) -> int:
        return int(self._clock() - self._started_at)

    def opening(self) -> list[str]:
        self._started_at = self._clock()
        self.state = InterviewState.ASKING
        greeting = OPENING_TEMPLATE.format(role=self._role)
        self._record(Speaker.AGENT, greeting, None)  # the notice is part of the saved record
        return [greeting, *self._advance_to_next_question()]

    def handle_candidate_utterance(self, raw_text: str) -> list[str]:
        """Process one finished candidate utterance; return the sentences the agent should speak."""
        if self.state is not InterviewState.ASKING:
            return []
        self._idle_prompts = 0
        clean = sanitise_untrusted(raw_text, max_chars=3000)
        if not clean.text:
            return []
        question = self.current_question
        self._record(Speaker.CANDIDATE, clean.text, question, flags=clean.flags)
        if "possible_prompt_injection" in clean.flags:
            self._flag("possible_prompt_injection_in_answer")

        if self.elapsed_seconds >= self._settings.max_interview_seconds:
            return self._end(EndReason.TIME_LIMIT, TIME_LIMIT_LINE)

        words = clean.text.split()
        if len(words) <= _MAX_INTENT_WORDS:
            if _STOP.search(clean.text):
                return self._end(EndReason.CANDIDATE_REQUESTED_STOP, STOP_LINE)
            if _REPEAT.search(clean.text) and question is not None:
                return self._speak_lines([question.text], question)
            if _SKIP.search(clean.text) and question is not None:
                self.skipped_question_ids.append(question.id)
                return [self._acknowledgement(), *self._advance_to_next_question()]

        if (
            question is not None
            and question.follow_up_allowed
            and self._followups_used < self._settings.max_followups_per_question
            and len(words) < self._settings.min_words_before_no_followup
            and "possible_prompt_injection" not in clean.flags
        ):
            self._followups_used += 1
            return self._speak_lines([self._followup(question, clean.text)], question)

        return [self._acknowledgement(), *self._advance_to_next_question()]

    def repeat_current_question(self) -> list[str]:
        """Say the current question again (it was cut off or not heard). Does not advance."""
        question = self.current_question
        if self.state is not InterviewState.ASKING or question is None:
            return []
        return self._speak_lines([question.text], question)

    def snapshot(self) -> OrchestratorSnapshot:
        return OrchestratorSnapshot(
            state=self.state,
            end_reason=self.end_reason,
            turns=tuple(self.turns),
            integrity_flags=tuple(self.integrity_flags),
            skipped_question_ids=tuple(self.skipped_question_ids),
            asked_question_ids=tuple(self.asked_question_ids),
            index=self._index,
            followups_used=self._followups_used,
            ack_cursor=self._ack_cursor,
            idle_prompts=self._idle_prompts,
        )

    def restore(self, snap: OrchestratorSnapshot) -> None:
        """Undo every change made since `snap`. Used when the candidate kept talking after a
        turn was processed: the half-answer is merged with the rest and processed once."""
        self.state = snap.state
        self.end_reason = snap.end_reason
        self.turns = list(snap.turns)
        self.integrity_flags = list(snap.integrity_flags)
        self.skipped_question_ids = list(snap.skipped_question_ids)
        self.asked_question_ids = list(snap.asked_question_ids)
        self._index = snap.index
        self._followups_used = snap.followups_used
        self._ack_cursor = snap.ack_cursor
        self._idle_prompts = snap.idle_prompts

    def on_idle(self) -> list[str]:
        """Called when the candidate has been silent for a while."""
        if self.state is not InterviewState.ASKING:
            return []
        self._idle_prompts += 1
        if self._idle_prompts >= 2:
            return self._end(EndReason.NO_RESPONSE, NO_RESPONSE_LINE)
        return self._speak_lines([IDLE_LINE], self.current_question)

    def on_time_limit(self) -> list[str]:
        if self.state is not InterviewState.ASKING:
            return []
        return self._end(EndReason.TIME_LIMIT, TIME_LIMIT_LINE)

    def mark_ended(self, reason: EndReason) -> None:
        """Used by the transport layer (disconnect, internal error). No speech."""
        if self.state is not InterviewState.ENDED:
            self.state = InterviewState.ENDED
            self.end_reason = reason

    # ------------------------------------------------------------ internals

    def _advance_to_next_question(self) -> list[str]:
        self._index += 1
        self._followups_used = 0
        question = self.current_question
        if question is None:
            return self._end(EndReason.COMPLETED, CLOSING_LINE)
        self.asked_question_ids.append(question.id)
        return self._speak_lines([question.text], question)

    def _end(self, reason: EndReason, line: str) -> list[str]:
        self._record(Speaker.AGENT, line, self.current_question)
        self.state = InterviewState.ENDED
        self.end_reason = reason
        return [line]

    def _speak_lines(self, lines: list[str], question: Question | None) -> list[str]:
        for line in lines:
            self._record(Speaker.AGENT, line, question)
        return lines

    def _acknowledgement(self) -> str:
        line = _ACKNOWLEDGEMENTS[self._ack_cursor % len(_ACKNOWLEDGEMENTS)]
        self._ack_cursor += 1
        return line

    def _followup(self, question: Question, answer: str) -> str:
        user = (
            f"Interview question: {question.text}\n\n"
            + wrap_untrusted("CANDIDATE_ANSWER", answer)
            + "\n\nWrite the single follow-up question now."
        )
        try:
            with self.trace_llm() if self.trace_llm else nullcontext():
                raw = self._llm.complete(
                    system=FOLLOWUP_SYSTEM,
                    user=user,
                    max_tokens=self._settings.llm_turn_max_tokens,
                    temperature=0.4,
                )
        except LanguageModelError:
            log.warning("followup_llm_failed", extra={"interview_id": str(self.interview_id)})
            return _FALLBACK_FOLLOWUP
        guarded = guard_spoken_output(raw, max_chars=220)
        if guarded.blocked:
            self._flag(f"agent_output_blocked:{guarded.reason}")
            return _FALLBACK_FOLLOWUP
        if not guarded.text.rstrip().endswith("?"):
            return _FALLBACK_FOLLOWUP
        return guarded.text

    def _record(
        self,
        speaker: Speaker,
        text: str,
        question: Question | None,
        flags: list[str] | None = None,
    ) -> None:
        self.turns.append(
            TranscriptTurn(
                speaker=speaker,
                text=text,
                question_id=question.id if question else None,
                flags=list(flags or []),
            )
        )

    def _flag(self, flag: str) -> None:
        if flag not in self.integrity_flags:
            self.integrity_flags.append(flag)
