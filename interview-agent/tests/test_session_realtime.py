from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from conftest import LONG_ANSWER

from interview_agent.config import Settings
from interview_agent.llm import ScriptedModel
from interview_agent.models import EndReason, QuestionSet
from interview_agent.orchestrator import InterviewOrchestrator
from interview_agent.ports import TranscriptEvent
from interview_agent.session import VoiceSession
from interview_agent.sinks import LocalFileSink
from interview_agent.speech import SilentTextToSpeech
from interview_agent.summariser import InterviewSummariser


class QueueTransport:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.json_out: list[dict[str, Any]] = []
        self.bytes_out = 0

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.json_out.append(payload)

    async def send_bytes(self, data: bytes) -> None:
        self.bytes_out += len(data)

    async def receive(self) -> dict[str, Any]:
        return await self.inbox.get()


class ScriptedStt:
    """Yields events pushed by the test, ignoring the audio input."""

    def __init__(self) -> None:
        self.events: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        while (event := await self.events.get()) is not None:
            yield event


class SlowTts:
    """Emits many chunks slowly so a barge-in can interrupt it."""

    def __init__(self) -> None:
        self.chunks_sent = 0

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        for _ in range(200):
            self.chunks_sent += 1
            yield b"\x00" * 320
            await asyncio.sleep(0.01)


def build(
    question_set: QuestionSet, settings: Settings, stt: Any, tts: Any
) -> tuple[VoiceSession, QueueTransport]:
    llm = ScriptedModel()
    transport = QueueTransport()
    session = VoiceSession(
        orchestrator=InterviewOrchestrator(
            interview_id=question_set.interview_id,
            question_set=question_set,
            role_title="Engineer",
            llm=llm,
            settings=settings,
        ),
        summariser=InterviewSummariser(llm, settings),
        stt=stt,
        tts=tts,
        transport=transport,
        sink=LocalFileSink(settings.output_dir),
        settings=settings,
    )
    return session, transport


async def test_disconnect_saves_partial_record(
    question_set: QuestionSet, settings: Settings
) -> None:
    session, transport = build(question_set, settings, ScriptedStt(), SilentTextToSpeech())
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.2)
    await transport.inbox.put(
        {"type": "json", "data": {"type": "utterance", "text": "Hello, I am a developer."}}
    )
    await asyncio.sleep(0.2)
    await transport.inbox.put({"type": "disconnect"})
    record = await asyncio.wait_for(task, 10)
    assert record.summary.end_reason is EndReason.CANDIDATE_DISCONNECTED
    saved = Path(settings.output_dir) / f"{question_set.interview_id}.json"
    assert json.loads(saved.read_text("utf-8"))["summary"]["end_reason"] == "candidate_disconnected"


async def test_speech_path_debounces_split_finals_into_one_turn(
    question_set: QuestionSet, settings: Settings
) -> None:
    stt = ScriptedStt()
    session, transport = build(question_set, settings, stt, SilentTextToSpeech())
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.2)
    # Two finals close together (a pause mid-answer) must be answered once, not twice.
    await stt.events.put(TranscriptEvent("I work mostly with", True, 0.9))
    await stt.events.put(TranscriptEvent(LONG_ANSWER, True, 0.9))
    await asyncio.sleep(0.5)
    agent_texts = [m["text"] for m in transport.json_out if m["type"] == "agent_text"]
    assert agent_texts.count(question_set.questions[1].text) == 1
    await transport.inbox.put({"type": "json", "data": {"type": "end"}})
    record = await asyncio.wait_for(task, 10)
    candidate_turns = [t for t in record.transcript if t.speaker == "candidate"]
    assert len(candidate_turns) == 1 and candidate_turns[0].text.startswith("I work mostly with")


async def test_barge_in_stops_agent_audio_and_sends_clear(
    question_set: QuestionSet, settings: Settings
) -> None:
    stt, tts = ScriptedStt(), SlowTts()
    session, transport = build(question_set, settings, stt, tts)
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.15)  # agent is mid-greeting
    sent_before = tts.chunks_sent
    await stt.events.put(TranscriptEvent("wait let me ask something", False))
    await asyncio.sleep(0.2)
    assert {"type": "clear"} in transport.json_out
    frozen = tts.chunks_sent
    await asyncio.sleep(0.2)
    assert tts.chunks_sent == frozen and frozen >= sent_before  # no more audio after the interrupt
    await transport.inbox.put({"type": "disconnect"})
    await asyncio.wait_for(task, 10)
