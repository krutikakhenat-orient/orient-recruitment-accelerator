"""One interview over one WebSocket, run as a Pipecat pipeline.

    browser <-ws-> FastAPIWebsocketTransport -> Transcribe -> turn aggregator -> flow -> Polly

What Pipecat provides here (instead of the hand-written timers in the legacy `session.py`):

* Silero voice-activity detection, and the smart-turn model that judges from the audio whether
  the candidate has finished or is only pausing to think.
* Interruption handling: the candidate's speech stops the agent's audio immediately.
* Per-turn tracing of speech-to-text and text-to-speech latency (OpenTelemetry).

What stays ours: the approved-question flow (`InterviewOrchestrator`), the overlap repairs
(`voice.flow`), result summarising/persistence, and the browser wire format.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import (
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from ..config import Settings
from ..models import EndReason, InterviewRecord
from ..observability import llm_span
from ..orchestrator import InterviewOrchestrator, InterviewState
from ..ports import ResultSink, TextToSpeech
from ..summariser import InterviewSummariser
from .processors import (
    InterviewFlowProcessor,
    SpeechProgressTap,
    TranscriptTap,
    span_context_getter,
)
from .serializer import InterviewWireSerializer
from .services import PortTTSService, build_stt

log = logging.getLogger(__name__)

# Ends a turn that has gone quiet even if no end-of-turn decision was made.
_TURN_STOP_TIMEOUT_SECONDS = 6.0


class PipecatVoiceSession:
    def __init__(
        self,
        *,
        websocket: WebSocket,
        orchestrator: InterviewOrchestrator,
        summariser: InterviewSummariser,
        tts: TextToSpeech,
        sink: ResultSink,
        settings: Settings,
    ) -> None:
        self._websocket = websocket
        self._orch = orchestrator
        self._summariser = summariser
        self._tts_port = tts
        self._sink = sink
        self._settings = settings
        self._id = str(orchestrator.interview_id)

    # ------------------------------------------------------------ build

    def _aggregator(self) -> LLMUserAggregator:
        s = self._settings
        if s.adapters == "aws":
            vad: SileroVADAnalyzer | None = SileroVADAnalyzer(
                params=VADParams(stop_secs=s.vad_stop_secs)
            )
            stop: Any = TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=LocalSmartTurnAnalyzerV3(
                    params=SmartTurnParams(stop_secs=s.turn_max_pause_secs)
                )
            )
        else:
            # Local/test: "audio" is text, so there is no voice activity to analyse. A short
            # timer after the transcript ends the turn instead.
            vad = None
            stop = SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.3)
        return LLMUserAggregator(
            LLMContext(),
            params=LLMUserAggregatorParams(
                vad_analyzer=vad,
                user_turn_strategies=UserTurnStrategies(
                    start=[MinWordsUserTurnStartStrategy(min_words=s.barge_in_min_words)],
                    stop=[stop],
                ),
                user_turn_stop_timeout=_TURN_STOP_TIMEOUT_SECONDS,
                empty_user_turn=None,
            ),
        )

    async def run(self) -> InterviewRecord:
        s = self._settings
        orch = self._orch

        transport = FastAPIWebsocketTransport(
            websocket=self._websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=s.sample_rate_hz,
                audio_out_sample_rate=s.sample_rate_hz,
                audio_out_end_silence_secs=0,
                audio_out_auto_silence=False,
                serializer=InterviewWireSerializer(sample_rate=s.sample_rate_hz),
                # The caller was authenticated by AgentCore (SigV4) and holds a single-use join
                # token; an Origin allow-list here would only break browser connections.
                allowed_origins=[],
            ),
        )

        flow = InterviewFlowProcessor(
            orchestrator=orch, settings=s, interview_id=self._id
        )
        # The follow-up wording is the only model call; trace it as a GenAI span.
        orch.trace_llm = lambda: llm_span(
            s,
            interview_id=self._id,
            purpose="follow_up_wording",
            parent=flow.controller._turn_context(),
        )

        aggregator = self._aggregator()

        @aggregator.event_handler("on_user_turn_stopped")  # type: ignore[untyped-decorator]
        async def _turn_stopped(_agg: Any, _strategy: Any, message: Any) -> None:
            text = (message.content or "").strip()
            if text:
                flow.submit_turn(text)

        pipeline = Pipeline(
            [
                transport.input(),
                build_stt(s),
                TranscriptTap(lambda: flow.controller),
                aggregator,
                flow,
                PortTTSService(port=self._tts_port, settings=s),
                SpeechProgressTap(lambda: flow.controller),
                transport.output(),
            ]
        )
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=s.sample_rate_hz,
                audio_out_sample_rate=s.sample_rate_hz,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            enable_tracing=s.otel_enabled,
            enable_turn_tracking=True,
            # Pipecat's RTVI client protocol is not used (the browser speaks the wire format in
            # serializer.py). Left on, it intercepts our messages and logs their content.
            enable_rtvi=False,
            conversation_id=self._id,
            additional_span_attributes={"session.id": self._id, "interview.id": self._id},
            # Silence and the time limit are handled by the flow controller, with a recorded
            # end reason; Pipecat's own idle cancel would end the call without one.
            idle_timeout_secs=None,
            cancel_on_idle_timeout=False,
        )
        flow.set_turn_context(span_context_getter(worker))

        @worker.event_handler("on_pipeline_started")  # type: ignore[untyped-decorator]
        async def _started(_worker: Any, _frame: Any) -> None:
            flow.create_task(flow.controller.start(), name="interview-start")

        @transport.event_handler("on_client_disconnected")  # type: ignore[untyped-decorator]
        async def _disconnected(_transport: Any, _ws: Any) -> None:
            if flow.controller.ended:
                return  # a normal end is already shutting the pipeline down
            await flow.controller.on_disconnect()
            await worker.cancel(reason="client_disconnected")

        try:
            runner = WorkerRunner(handle_sigint=False)
            await runner.add_workers(worker)
            await runner.run()
        except asyncio.CancelledError:
            orch.mark_ended(EndReason.ERROR)
            raise
        except Exception as exc:  # noqa: BLE001 - recorded as an error end; data is still saved
            log.error("pipeline_failed", extra={"interview_id": self._id, "error": type(exc).__name__})
            orch.mark_ended(EndReason.ERROR)
        finally:
            await flow.controller.close()

        if orch.state is not InterviewState.ENDED:
            orch.mark_ended(EndReason.ERROR)  # the pipeline stopped for a reason we did not set

        summary = await asyncio.to_thread(self._summariser.summarise, orch)
        record = InterviewRecord(summary=summary, transcript=orch.turns)
        location = await asyncio.to_thread(self._sink.persist, record)
        log.info("interview_persisted", extra={"interview_id": self._id, "location": location})
        return record
