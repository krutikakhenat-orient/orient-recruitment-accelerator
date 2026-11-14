"""AgentCore Runtime HTTP contract: GET /ping, POST /invocations, WebSocket /ws on port 8080.

Inbound authentication (SigV4 or OAuth) is enforced by AgentCore Runtime in front of this app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Settings, get_settings
from .models import PlanQuestionsRequest, PrepareSessionRequest, QuestionSet
from .observability import init_observability
from .orchestrator import InterviewOrchestrator
from .runtime import Runtime, build_runtime
from .session import VoiceSession

if TYPE_CHECKING:
    from .voice.session import PipecatVoiceSession

log = logging.getLogger("interview_agent")

_MAX_TEXT_FRAME = 10_000
_MAX_AUDIO_FRAME = 64_000
_START_TIMEOUT_SECONDS = 15

Invocation = Annotated[PlanQuestionsRequest | PrepareSessionRequest, Field(discriminator="action")]


class StartMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["start"]
    interview_id: UUID
    join_token: str = Field(min_length=16, max_length=128)


class PreparedResponse(BaseModel):
    status: Literal["ready"] = "ready"
    interview_id: UUID
    join_token: str


class WebSocketTransport:
    """Adapts a Starlette WebSocket to the Transport port with frame size limits."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._ws.send_json(payload)

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)

    async def receive(self) -> dict[str, Any]:
        while True:
            message = await self._ws.receive()
            if message["type"] == "websocket.disconnect":
                return {"type": "disconnect"}
            if message.get("bytes") is not None:
                data = message["bytes"]
                if len(data) <= _MAX_AUDIO_FRAME:
                    return {"type": "audio", "data": data}
                continue  # oversized frame: ignore
            text = message.get("text")
            if text is not None and len(text) <= _MAX_TEXT_FRAME:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return {"type": "json", "data": parsed}


def _error(status: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
        headers={"X-Correlation-Id": correlation_id},
    )


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()
    rt = runtime or build_runtime(settings)
    tracing_mode = init_observability(settings)
    log.info("observability_ready", extra={"tracing": tracing_mode, "engine": settings.voice_engine})
    app = FastAPI(title="Interview Agent", docs_url=None, redoc_url=None, openapi_url=None)
    started = int(time.time())

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "validation_error", "Request failed validation.", _cid(request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        cid = _cid(request)
        log.error("unhandled_error", extra={"correlation_id": cid, "error": type(exc).__name__})
        return _error(500, "internal_error", "Internal error.", cid)

    if settings.environment == "local":
        # Local test page only. Not served in dev/prod, and it self-approves question sets.
        page = (Path(__file__).parent / "dev_client.html").read_text(encoding="utf-8")

        @app.get("/dev", response_class=HTMLResponse)
        def dev_client() -> str:
            return page

    @app.get("/ping")
    def ping() -> dict[str, object]:
        return {"status": "Healthy", "time_of_last_update": started}

    @app.post("/invocations", response_model=None)
    def invocations(
        payload: Invocation, request: Request
    ) -> QuestionSet | PreparedResponse | JSONResponse:
        """Permission: caller must hold bedrock-agentcore:InvokeAgentRuntime (HR backend role)."""
        cid = _cid(request)
        if isinstance(payload, PlanQuestionsRequest):
            return rt.planner.plan(payload)  # synchronous; FastAPI runs this in a worker thread

        if not payload.consent_given:
            return _error(422, "consent_required", "Candidate consent is required.", cid)
        if not payload.question_set.approved:
            return _error(
                422, "question_set_not_approved", "A human must approve the questions.", cid
            )
        if payload.question_set.interview_id != payload.interview_id:
            return _error(
                422, "interview_mismatch", "Question set belongs to another interview.", cid
            )
        token = rt.registry.put(payload.interview_id, payload.question_set, payload.role_title)
        return PreparedResponse(interview_id=payload.interview_id, join_token=token)

    @app.websocket("/ws")
    async def interview_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(_first_json_message(websocket), timeout=_START_TIMEOUT_SECONDS)
            start = StartMessage.model_validate(raw)
        except (TimeoutError, ValidationError, ValueError, KeyError):
            await _close_with_error(websocket, "invalid_start")
            return
        prepared = rt.registry.take(start.interview_id, start.join_token)
        if prepared is None:
            await _close_with_error(websocket, "interview_not_available")
            return

        orchestrator = InterviewOrchestrator(
            interview_id=start.interview_id,
            question_set=prepared.question_set,
            role_title=prepared.role_title,
            llm=rt.llm,
            settings=settings,
        )
        await websocket.send_json(
            {
                "type": "ready",
                "audio": {
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": settings.sample_rate_hz,
                    "channels": 1,
                },
                "text_input": settings.allow_text_input,
            }
        )
        session: VoiceSession | PipecatVoiceSession
        if settings.voice_engine == "pipecat":
            # Imported here so the legacy engine (and tools that only plan questions) do not
            # load Pipecat and its models.
            from .voice.session import PipecatVoiceSession

            session = PipecatVoiceSession(
                websocket=websocket,
                orchestrator=orchestrator,
                summariser=rt.summariser,
                tts=rt.tts,
                sink=rt.sink,
                settings=settings,
            )
        else:
            session = VoiceSession(
                orchestrator=orchestrator,
                summariser=rt.summariser,
                stt=rt.stt,
                tts=rt.tts,
                transport=WebSocketTransport(websocket),
                sink=rt.sink,
                settings=settings,
            )
        try:
            await session.run()
        except Exception as exc:  # noqa: BLE001 - reported to client without detail, logged by type
            log.error(
                "session_failed",
                extra={"interview_id": str(start.interview_id), "error": type(exc).__name__},
            )
            await _safe_close(websocket, {"type": "error", "code": "session_failed"})
            return
        await _safe_close(websocket, None)

    return app


async def _first_json_message(websocket: WebSocket) -> object:
    """Return the first JSON text frame. Binary (audio) frames that a client sends before its
    "start" message are discarded rather than failing the connection. A disconnect or a
    non-JSON text frame still fails, so the caller's timeout bounds the wait."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise ValueError("disconnected_before_start")
        text = message.get("text")
        if text is None:
            continue  # early audio frame
        if len(text) > _MAX_TEXT_FRAME:
            raise ValueError("start_frame_too_large")
        return json.loads(text)


def _cid(request: Request) -> str:
    return request.headers.get("x-correlation-id") or str(uuid.uuid4())


async def _close_with_error(websocket: WebSocket, code: str) -> None:
    await _safe_close(websocket, {"type": "error", "code": code})


async def _safe_close(websocket: WebSocket, payload: dict[str, str] | None) -> None:
    try:
        if payload:
            await websocket.send_json(payload)
        await websocket.close()
    except Exception:  # noqa: BLE001 - client already gone
        log.debug("websocket_close_failed")


def create_default_app() -> FastAPI:
    """Factory for uvicorn: `uvicorn interview_agent.app:create_default_app --factory`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
