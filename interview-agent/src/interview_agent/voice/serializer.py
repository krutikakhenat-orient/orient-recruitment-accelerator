"""Wire format between the candidate's browser and the agent (unchanged from the first version).

Binary frames  -> raw 16 kHz mono PCM s16le audio, both directions.
Text frames    -> JSON control messages. Client -> agent: ``utterance`` (typed answer) and
                  ``end``. Agent -> client: ``ready``, ``transcript``, ``agent_text``,
                  ``agent_audio_end``, ``clear`` (stop playing queued audio), ``warning``,
                  ``ended`` and ``error``.

Keeping this contract identical means the browser page (`AiInterviewPage.tsx`) and the HR
backend that signs the WebSocket URL need no change when the voice engine changes.

Security: frame sizes are capped, non-JSON and non-object text frames are dropped, and nothing
from the client is trusted as a Pipecat frame type; only audio and a small message dict get in.
"""

from __future__ import annotations

import json
from typing import Any

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

MAX_TEXT_FRAME = 10_000
MAX_AUDIO_FRAME = 64_000


class InterviewWireSerializer(FrameSerializer):
    def __init__(self, *, sample_rate: int) -> None:
        super().__init__()
        self._sample_rate = sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return json.dumps(frame.message, separators=(",", ":"))
        if isinstance(frame, InterruptionFrame):
            # Tell the browser to drop audio it has queued but not yet played.
            return json.dumps({"type": "clear"})
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            if not data or len(data) > MAX_AUDIO_FRAME:
                return None  # empty or oversized: ignore rather than fail the call
            return InputAudioRawFrame(
                audio=bytes(data), sample_rate=self._sample_rate, num_channels=1
            )
        if len(data) > MAX_TEXT_FRAME:
            return None
        try:
            parsed: Any = json.loads(data)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return InputTransportMessageFrame(message=parsed)
