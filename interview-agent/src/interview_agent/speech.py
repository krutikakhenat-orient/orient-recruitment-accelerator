"""Speech adapters: Amazon Transcribe streaming (STT) and Amazon Polly (TTS), plus local fakes."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from .config import Settings
from .ports import TranscriptEvent

_PCM_CHUNK_BYTES = 3200  # 100 ms of 16 kHz mono 16-bit audio


def _boto3_credential_resolver_base() -> Any:
    from amazon_transcribe.auth import CredentialResolver

    return CredentialResolver


class _Boto3CredentialResolver(_boto3_credential_resolver_base()):  # type: ignore[misc]
    """Gives Transcribe the same credentials boto3 uses.

    The Transcribe SDK's own resolver (awscrt) does not understand SSO or assume-role profiles
    and falls through to the EC2 metadata service. boto3 handles all of those and refreshes
    temporary credentials, so we ask it each time the SDK needs credentials.
    """

    def __init__(self) -> None:
        import boto3

        # One credentials object per stream. The connection and every audio event in it are
        # signed with the same key chain; a new session per call can yield different temporary
        # keys (assume-role/SSO profiles), which Transcribe rejects as a signature mismatch.
        found = boto3.Session().get_credentials()
        if found is None:
            raise RuntimeError("no_aws_credentials")
        self._frozen = found.get_frozen_credentials()

    async def get_credentials(self) -> Any:
        from amazon_transcribe.auth import Credentials

        frozen = self._frozen
        return Credentials(
            access_key_id=frozen.access_key,
            secret_access_key=frozen.secret_key,
            session_token=frozen.token,
        )


class TranscribeSpeechToText:
    """Streams PCM to Transcribe and yields partial/final transcripts.

    Partial-result stabilisation is on so partials are usable for barge-in detection.
    """

    def __init__(self, settings: Settings) -> None:
        self._region = settings.aws_region
        self._language = settings.transcribe_language
        self._rate = settings.sample_rate_hz

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler

        client = TranscribeStreamingClient(
            region=self._region, credential_resolver=_Boto3CredentialResolver()
        )
        session = await client.start_stream_transcription(
            language_code=self._language,
            media_sample_rate_hz=self._rate,
            media_encoding="pcm",
            enable_partial_results_stabilization=True,
            partial_results_stability="high",
        )
        queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

        class _Handler(TranscriptResultStreamHandler):  # type: ignore[misc]
            async def handle_transcript_event(self, transcript_event: Any) -> None:
                for result in transcript_event.transcript.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    text = (alt.transcript or "").strip()
                    if not text:
                        continue
                    confidences = [
                        float(c)
                        for c in (getattr(i, "confidence", None) for i in (alt.items or []))
                        if c is not None
                    ]
                    avg = sum(confidences) / len(confidences) if confidences else None
                    await queue.put(TranscriptEvent(text, not result.is_partial, avg))

        async def feed() -> None:
            try:
                async for chunk in audio:
                    await session.input_stream.send_audio_event(audio_chunk=chunk)
            finally:
                with contextlib.suppress(Exception):
                    await session.input_stream.end_stream()

        async def drain() -> None:
            try:
                await _Handler(session.output_stream).handle_events()
            finally:
                await queue.put(None)

        feeder = asyncio.create_task(feed())
        drainer = asyncio.create_task(drain())
        try:
            while (event := await queue.get()) is not None:
                yield event
            drainer.result()  # surface Transcribe errors instead of ending silently
        finally:
            feeder.cancel()
            drainer.cancel()
            await asyncio.gather(feeder, drainer, return_exceptions=True)


class PollyTextToSpeech:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("polly", region_name=settings.polly_region or settings.aws_region)
        self._client = client
        self._settings = settings

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        s = self._settings
        response = await asyncio.to_thread(
            self._client.synthesize_speech,
            Text=text[:3000],
            TextType="text",
            OutputFormat="pcm",
            SampleRate=str(s.sample_rate_hz),
            VoiceId=s.polly_voice_id,
            Engine=s.polly_engine,
            LanguageCode=s.polly_language_code,
        )
        body = response["AudioStream"]
        try:
            while chunk := await asyncio.to_thread(body.read, _PCM_CHUNK_BYTES):
                yield chunk
        finally:
            body.close()


class FakeSpeechToText:
    """Local stand-in: every audio chunk is treated as UTF-8 text and returned as a final result."""

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        async for chunk in audio:
            text = chunk.decode("utf-8", errors="ignore").strip()
            if text:
                yield TranscriptEvent(text, True, 1.0)


class SilentTextToSpeech:
    """Local stand-in: 100 ms of silence per sentence so the audio path is exercised."""

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        yield b"\x00" * _PCM_CHUNK_BYTES
