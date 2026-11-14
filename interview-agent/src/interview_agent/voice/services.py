"""Pipecat speech services for the interview agent.

* `PrivateTranscribeSTTService` - Amazon Transcribe streaming through Pipecat. Pipecat's own
  class records every transcript as a tracing-span attribute; this subclass removes that so
  candidate speech never lands in CloudWatch (see `observability.py`).
* `PortTTSService` - wraps the project's `TextToSpeech` port (Amazon Polly in production, a
  silent stand-in locally). Polly's proven voice/engine/region settings are kept as they are.
* `FakeTextSTT` - local/test stand-in: each binary "audio" frame is read as UTF-8 text.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from pipecat.frames.frames import Frame, InputAudioRawFrame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.aws.stt import AWSTranscribeSTTService
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from ..config import Settings
from ..ports import TextToSpeech

log = logging.getLogger(__name__)

# 100 ms of 16 kHz mono 16-bit audio per chunk keeps playback and interruption responsive.
_TTS_CHUNK_BYTES = 3200


class PrivateTranscribeSTTService(AWSTranscribeSTTService):
    async def _handle_transcription(
        self, transcript: str, is_final: bool, language: str | None = None
    ) -> None:
        # Deliberately empty. The base class method is only a tracing hook that would put the
        # transcript into a span attribute. Candidate speech must not be exported.
        return None


class PortTTSService(TTSService):
    """Pipecat TTS service backed by a `TextToSpeech` port (16 kHz mono PCM chunks)."""

    def __init__(self, *, port: TextToSpeech, settings: Settings) -> None:
        super().__init__(
            sample_rate=settings.sample_rate_hz,
            push_start_frame=True,
            push_stop_frames=True,
            # Report "this line has been produced" soon after its last audio chunk; the flow
            # controller uses it to tell a pause between two lines from the end of speech.
            stop_frame_timeout_s=0.3,
            settings=TTSSettings(model=None, voice=settings.polly_voice_id, language=None),
        )
        self._port = port

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        try:
            await self.start_tts_usage_metrics(text)
            first = True
            async for chunk in self._port.synthesize(text):
                if first:
                    await self.stop_ttfb_metrics()
                    first = False
                for i in range(0, len(chunk), _TTS_CHUNK_BYTES):
                    piece = chunk[i : i + _TTS_CHUNK_BYTES]
                    if piece:
                        yield TTSAudioRawFrame(piece, self.sample_rate, 1, context_id=context_id)
        except Exception as exc:  # noqa: BLE001 - one failed sentence must not end the interview
            # Log the exception type only: the text being spoken is not logged.
            log.error("tts_failed", extra={"error": type(exc).__name__})


class FakeTextSTT(FrameProcessor):
    """Treats each audio frame as UTF-8 text and emits it as a final transcript."""

    def __init__(self) -> None:
        super().__init__()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            text = frame.audio.decode("utf-8", errors="ignore").strip()
            if text:
                await self.push_frame(
                    TranscriptionFrame(
                        text=text,
                        user_id="candidate",
                        timestamp=datetime.now(UTC).isoformat(),
                        language=Language.EN,
                    )
                )
            return  # audio is consumed here, like a real STT service would
        await self.push_frame(frame, direction)


def build_stt(settings: Settings) -> FrameProcessor:
    if settings.adapters == "aws":
        return PrivateTranscribeSTTService(
            region=settings.aws_region,
            sample_rate=settings.sample_rate_hz,
            settings=PrivateTranscribeSTTService.Settings(
                language=Language(settings.transcribe_language),
                partial_results_stability="high",
            ),
        )
    return FakeTextSTT()
