"""Conversation mechanics (voice/flow.py): listening, overlap repair, silence, ending.

All data is SYNTHETIC. The controller is tested without Pipecat: speech, notifications and
"finish" are recorded by a small harness, and time is a fake clock.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from conftest import LONG_ANSWER

from interview_agent.config import Settings
from interview_agent.llm import ScriptedModel
from interview_agent.models import EndReason, QuestionSet, Speaker
from interview_agent.orchestrator import InterviewOrchestrator, InterviewState
from interview_agent.voice import flow as flow_module
from interview_agent.voice.flow import FlowController, is_acknowledgement, is_thinking_filler


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Harness:
    def __init__(self, question_set: QuestionSet, settings: Settings) -> None:
        self.clock = FakeClock()
        self.spoken: list[list[str]] = []
        self.interrupts: list[bool] = []
        self.sent: list[dict[str, Any]] = []
        self.finished: list[bool] = []
        self.llm = ScriptedModel()
        self.orch = InterviewOrchestrator(
            interview_id=question_set.interview_id,
            question_set=question_set,
            role_title="Synthetic Backend Engineer",
            llm=self.llm,
            settings=settings,
            clock=self.clock,
        )
        self.ctl = FlowController(
            orchestrator=self.orch,
            settings=settings,
            interview_id=str(question_set.interview_id),
            speak=self._speak,
            notify=self._notify,
            finish=self._finish,
            clock=self.clock,
        )

    async def _speak(self, lines: list[str], *, interrupt: bool = False) -> None:
        self.spoken.append(list(lines))
        self.interrupts.append(interrupt)

    async def _notify(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def _finish(self, graceful: bool) -> None:
        self.finished.append(graceful)

    async def play_all(self) -> None:
        """Simulate the voice playing everything that was last queued, to the end."""
        self.ctl.on_bot_started()
        for _ in self.spoken[-1]:
            self.ctl.on_tts_line_synthesised()
        self.clock.advance(20)
        await self.ctl.on_bot_stopped()

    def candidate_turns(self) -> list[str]:
        return [t.text for t in self.orch.turns if t.speaker is Speaker.CANDIDATE]

    def agent_turns(self) -> list[str]:
        return [t.text for t in self.orch.turns if t.speaker is Speaker.AGENT]


@pytest.fixture
def h(question_set: QuestionSet, settings: Settings) -> Harness:
    return Harness(question_set, settings)


# ------------------------------------------------------------------ classification


@pytest.mark.parametrize("text", ["um", "Hmm...", "uh, um", "well um"])
def test_thinking_noises_are_fillers(text: str) -> None:
    assert is_thinking_filler(text)


@pytest.mark.parametrize(
    "text",
    ["I used Python", "yes", "um I think we used Kafka", "no"],
)
def test_real_content_is_not_a_filler(text: str) -> None:
    assert not is_thinking_filler(text)


@pytest.mark.parametrize("text", ["okay", "yeah sure", "sorry, what?", "um okay"])
def test_acknowledgements(text: str) -> None:
    assert is_acknowledgement(text)


def test_a_sentence_is_not_an_acknowledgement() -> None:
    assert not is_acknowledgement("okay so I worked on a payments platform")


# ------------------------------------------------------------------ opening and answers


async def test_opening_greets_and_asks_the_first_question(h: Harness) -> None:
    await h.ctl.start()
    assert len(h.spoken) == 1
    assert "automated interviewer" in h.spoken[0][0]
    assert h.spoken[0][1] == "Please introduce yourself briefly."
    # The notice the candidate heard is part of the saved record.
    assert "automated interviewer" in h.agent_turns()[0]


async def test_a_finished_answer_moves_to_the_next_question(h: Harness) -> None:
    await h.ctl.start()
    await h.ctl.on_user_turn(LONG_ANSWER)
    assert h.spoken[-1][-1] == "Describe a project where you used Python."
    assert h.orch.asked_question_ids == ["std-intro", "q1"]


async def test_thinking_noise_is_not_an_answer(h: Harness) -> None:
    await h.ctl.start()
    spoken_before = len(h.spoken)
    await h.ctl.on_user_turn("um, hmm")
    assert len(h.spoken) == spoken_before
    assert h.candidate_turns() == []
    assert h.orch.asked_question_ids == ["std-intro"]


async def test_yes_is_a_real_answer_when_the_question_was_fully_heard(h: Harness) -> None:
    await h.ctl.start()
    h.ctl.on_bot_started()
    h.ctl.on_tts_line_synthesised()
    h.ctl.on_tts_line_synthesised()  # greeting and question both produced
    h.clock.advance(20)
    await h.ctl.on_bot_stopped()
    assert {"type": "agent_audio_end"} in h.sent
    await h.ctl.on_user_turn("yes")
    assert h.candidate_turns() == ["yes"]


async def test_a_pause_between_two_lines_is_not_the_end_of_speech(h: Harness) -> None:
    await h.ctl.start()  # two lines: greeting, then the first question
    h.ctl.on_bot_started()
    h.ctl.on_tts_line_synthesised()  # the greeting is produced; the question is still coming
    h.clock.advance(3)
    await h.ctl.on_bot_stopped()  # output went quiet for a moment
    assert {"type": "agent_audio_end"} not in h.sent
    # So an "okay" now still counts as talking over the agent, not as an answer.
    await h.ctl.on_user_turn("okay")
    assert h.candidate_turns() == []


# ------------------------------------------------------------------ cut off while asking


async def test_cut_off_question_and_bare_okay_asks_it_again(h: Harness) -> None:
    await h.ctl.start()
    h.ctl.on_bot_started()
    h.clock.advance(0.4)
    h.ctl.on_interrupted()  # candidate spoke over the question after 0.4 s
    await h.ctl.on_user_turn("okay")
    assert h.spoken[-1] == ["Please introduce yourself briefly."]
    assert h.candidate_turns() == []  # "okay" was not recorded as an answer
    assert h.orch.asked_question_ids == ["std-intro"]  # not advanced


async def test_interrupt_before_any_audio_played_also_repeats(h: Harness) -> None:
    await h.ctl.start()
    h.ctl.on_interrupted()  # never started playing
    await h.ctl.on_user_turn("sorry, what?")
    assert h.spoken[-1] == ["Please introduce yourself briefly."]


async def test_acknowledgement_while_agent_is_talking_is_ignored(h: Harness) -> None:
    await h.ctl.start()
    h.ctl.on_bot_started()
    h.clock.advance(0.2)
    spoken_before = len(h.spoken)
    await h.ctl.on_user_turn("okay")
    assert len(h.spoken) == spoken_before
    assert h.candidate_turns() == []


# ------------------------------------------------------------------ candidate keeps talking


async def test_talking_over_the_reply_immediately_extends_the_previous_answer(h: Harness) -> None:
    await h.ctl.start()
    await h.ctl.on_user_turn(LONG_ANSWER)  # -> Q1 (follow-ups allowed)
    h.clock.advance(1)
    # A short, thin answer to Q1 triggers a follow-up question.
    await h.ctl.on_user_turn("I built an API")
    assert h.spoken[-1] == ["Could you give a specific example?"]
    h.ctl.on_bot_started()
    h.clock.advance(0.5)
    h.ctl.on_interrupted()  # candidate was not finished
    await h.ctl.on_user_turn("using FastAPI with PostgreSQL and a full test suite behind it")

    merged = h.candidate_turns()[-1]
    assert merged.startswith("I built an API using FastAPI")
    # The cut-off follow-up is gone from the record; the answer exists once.
    assert h.candidate_turns().count("I built an API") == 0
    assert h.agent_turns().count("Could you give a specific example?") <= 1


async def test_words_arriving_while_a_turn_is_processed_are_merged(
    question_set: QuestionSet, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness(question_set, settings)
    await h.ctl.start()
    spoken_before = len(h.spoken)

    async def slow_blocking(fn: Any, *args: Any) -> Any:
        result = fn(*args)
        h.clock.advance(0.5)
        h.ctl.on_words_heard()  # the candidate started talking again meanwhile
        return result

    h.ctl._run_blocking = slow_blocking
    await h.ctl.on_user_turn(LONG_ANSWER)

    # Nothing was said, nothing was recorded, and the question was not marked as answered.
    assert len(h.spoken) == spoken_before
    assert h.candidate_turns() == []
    assert h.orch.asked_question_ids == ["std-intro"]

    h.ctl._run_blocking = asyncio.to_thread
    await h.ctl.on_user_turn("and then we shipped it to production")
    assert h.candidate_turns() == [f"{LONG_ANSWER} and then we shipped it to production"]
    assert h.spoken[-1][-1] == "Describe a project where you used Python."
    await h.ctl.close()  # drop the now-unneeded "flush deferred words" timer


async def test_deferred_words_are_processed_if_the_candidate_says_nothing_more(
    question_set: QuestionSet, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness(question_set, settings)
    await h.ctl.start()
    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(flow_module.asyncio, "sleep", fast_sleep)

    async def interrupted_once(fn: Any, *args: Any) -> Any:
        result = fn(*args)
        h.clock.advance(0.5)
        h.ctl.on_words_heard()  # a cough / noise transcribed as text, then silence
        return result

    h.ctl._run_blocking = interrupted_once
    await h.ctl.on_user_turn(LONG_ANSWER)
    h.ctl._run_blocking = asyncio.to_thread
    for _ in range(200):
        await real_sleep(0.005)
        if len(h.spoken) >= 2:
            break
    await h.ctl.close()
    assert h.candidate_turns() == [LONG_ANSWER]
    assert h.spoken[-1][-1] == "Describe a project where you used Python."


# ------------------------------------------------------------------ typed answers


async def test_typed_answer_cuts_off_the_agent_and_is_not_deferred(h: Harness) -> None:
    await h.ctl.start()
    h.ctl.on_words_heard()
    await h.ctl.on_user_turn(LONG_ANSWER, typed=True)
    assert h.interrupts[-1] is True
    assert h.candidate_turns() == [LONG_ANSWER]


# ------------------------------------------------------------------ silence and time


async def test_silence_prompts_once_then_ends(question_set: QuestionSet, settings: Settings) -> None:
    settings = settings.model_copy(update={"idle_prompt_seconds": 30})
    h = Harness(question_set, settings)
    await h.ctl.start()
    h.ctl.on_bot_started()
    h.clock.advance(20)
    await h.ctl.on_bot_stopped()
    h.clock.advance(settings.idle_prompt_seconds)
    await h.ctl.tick()
    assert "still there" in h.spoken[-1][0]
    assert not h.ctl.ended

    await h.play_all()
    h.clock.advance(settings.idle_prompt_seconds)
    await h.ctl.tick()
    assert h.orch.end_reason is EndReason.NO_RESPONSE
    assert h.finished == []  # the closing line is still playing
    await h.play_all()
    assert h.finished == [True]
    assert h.sent[-1] == {"type": "ended", "reason": "no_response"}


async def test_no_idle_prompt_while_the_candidate_is_talking(
    question_set: QuestionSet, settings: Settings
) -> None:
    settings = settings.model_copy(update={"idle_prompt_seconds": 30})
    h = Harness(question_set, settings)
    await h.ctl.start()
    h.clock.advance(settings.idle_prompt_seconds - 1)
    h.ctl.on_words_heard()
    h.clock.advance(5)
    await h.ctl.tick()
    assert len(h.spoken) == 1  # only the opening


async def test_time_limit_closes_politely(
    question_set: QuestionSet, settings: Settings
) -> None:
    settings = settings.model_copy(update={"max_interview_seconds": 60})
    h = Harness(question_set, settings)
    await h.ctl.start()
    h.clock.advance(61)
    await h.ctl.tick()
    assert h.orch.end_reason is EndReason.TIME_LIMIT
    assert "time limit" in h.spoken[-1][0]
    await h.play_all()
    assert h.finished == [True]


# ------------------------------------------------------------------ ending


async def test_candidate_asking_to_stop_ends_gracefully(h: Harness) -> None:
    await h.ctl.start()
    await h.ctl.on_user_turn("I want to stop this interview now")
    assert h.orch.end_reason is EndReason.CANDIDATE_REQUESTED_STOP
    await h.play_all()
    assert h.finished == [True]
    assert h.sent[-1]["type"] == "ended"
    # Nothing further is processed once the interview has ended.
    await h.ctl.on_user_turn(LONG_ANSWER)
    assert h.candidate_turns() == ["I want to stop this interview now"]


async def test_end_button_stops_immediately_without_speech(h: Harness) -> None:
    await h.ctl.start()
    spoken_before = len(h.spoken)
    await h.ctl.on_client_end()
    assert h.orch.end_reason is EndReason.CANDIDATE_REQUESTED_STOP
    assert h.finished == [False]
    assert len(h.spoken) == spoken_before


async def test_disconnect_marks_the_reason_and_stays_quiet(h: Harness) -> None:
    await h.ctl.start()
    await h.ctl.on_disconnect()
    assert h.orch.end_reason is EndReason.CANDIDATE_DISCONNECTED
    assert h.orch.state is InterviewState.ENDED
    assert h.finished == []  # the transport is already gone


async def test_error_ends_with_the_error_reason(h: Harness) -> None:
    await h.ctl.start()
    await h.ctl.on_error()
    assert h.orch.end_reason is EndReason.ERROR
    assert h.finished == [False]


async def test_a_whole_interview_completes(h: Harness) -> None:
    await h.ctl.start()
    for _ in range(3):
        await h.ctl.on_user_turn(LONG_ANSWER)
    assert h.orch.end_reason is EndReason.COMPLETED
    assert "completes the interview" in h.spoken[-1][-1]
    await h.play_all()
    assert h.finished == [True]


async def test_ended_is_sent_only_after_the_closing_line_has_played(h: Harness) -> None:
    await h.ctl.start()
    for _ in range(3):
        await h.ctl.on_user_turn(LONG_ANSWER)
    assert not any(m["type"] == "ended" for m in h.sent)
    await h.play_all()
    kinds = [m["type"] for m in h.sent]
    assert kinds[-2:] == ["agent_audio_end", "ended"]  # same order the browser always saw


async def test_ended_is_still_sent_if_the_voice_never_reports_finishing(h: Harness) -> None:
    await h.ctl.start()
    await h.ctl.on_user_turn("I want to stop this interview now")
    h.clock.advance(60)  # far past the expected length of the closing line
    await h.ctl.tick()
    assert h.finished == [True]
    assert h.sent[-1]["type"] == "ended"
