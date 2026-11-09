"""Port + adapters for talking to the ``interview-agent`` service.

The HR backend never imports agent code. It speaks the agent's documented HTTP contract:
``POST /invocations`` (``plan_questions`` / ``prepare_session``) and a candidate-side
WebSocket ``/ws``. Three adapters sit behind one interface:

* ``HttpInterviewAgentClient``      local / self-hosted agent reachable by URL
* ``AgentCoreInterviewAgentClient`` agent deployed on Amazon Bedrock AgentCore Runtime
* ``FakeInterviewAgentClient``      deterministic, offline (tests only)

Agent output is untrusted: callers validate it against a strict schema before storing it.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol
from urllib.parse import quote

from app.core.config import Settings
from app.core.errors import AppError

# Lifetime of the pre-signed AgentCore WebSocket URL handed to the candidate's browser.
_WS_URL_TTL_SECONDS = 60


class AgentUnavailableError(AppError):
    status_code = 502
    code = "ai_interview_agent_unavailable"


class InterviewAgentClient(Protocol):
    def plan_questions(
        self,
        *,
        interview_id: uuid.UUID,
        job_descriptions: list[dict[str, Any]],
        resume_text: str,
        candidate_ref: str,
        max_questions: int | None = None,
    ) -> dict[str, Any]:
        """Return the agent's QuestionSet (unapproved)."""

    def prepare_session(
        self,
        *,
        interview_id: uuid.UUID,
        question_set: dict[str, Any],
        role_title: str,
        consent_notice_version: str,
        runtime_session_id: str,
    ) -> str:
        """Prime the agent for one live interview. Returns the single-use ``join_token``."""

    def connection_url(self, *, runtime_session_id: str) -> str:
        """URL the candidate's browser opens for the live audio WebSocket."""


def runtime_session_id_for(session_id: uuid.UUID) -> str:
    """AgentCore needs a runtime session id of >= 33 chars. ``prepare_session`` and the
    WebSocket MUST use the same id so they reach the same isolated agent process."""
    return f"ora-ai-interview-{session_id}"


class HttpInterviewAgentClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.ai_interview_agent_base_url.rstrip("/")
        self._ws_url = settings.ai_interview_agent_ws_url
        self._timeout = settings.ai_interview_agent_timeout_seconds

    def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        try:
            response = httpx.post(f"{self._base}/invocations", json=body, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise AgentUnavailableError("The interview agent could not be reached.") from exc
        if response.status_code >= 300:
            raise AgentUnavailableError(
                f"The interview agent rejected the request (HTTP {response.status_code})."
            )
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise AgentUnavailableError("The interview agent returned an unexpected response.")
        return parsed

    def plan_questions(
        self,
        *,
        interview_id: uuid.UUID,
        job_descriptions: list[dict[str, Any]],
        resume_text: str,
        candidate_ref: str,
        max_questions: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "action": "plan_questions",
            "interview_id": str(interview_id),
            "job_descriptions": job_descriptions,
            "resume": {"candidate_ref": candidate_ref, "text": resume_text},
        }
        if max_questions is not None:
            body["max_questions"] = max_questions
        return self._invoke(body)

    def prepare_session(
        self,
        *,
        interview_id: uuid.UUID,
        question_set: dict[str, Any],
        role_title: str,
        consent_notice_version: str,
        runtime_session_id: str,  # noqa: ARG002 - only AgentCore routes by session id
    ) -> str:
        parsed = self._invoke(
            {
                "action": "prepare_session",
                "interview_id": str(interview_id),
                "question_set": question_set,
                "role_title": role_title,
                "consent_notice_version": consent_notice_version,
                "consent_given": True,
            }
        )
        token = parsed.get("join_token")
        if not isinstance(token, str) or not token:
            raise AgentUnavailableError("The interview agent did not return a join token.")
        return token

    def connection_url(self, *, runtime_session_id: str) -> str:  # noqa: ARG002
        return self._ws_url


class AgentCoreInterviewAgentClient:
    """Agent deployed on Amazon Bedrock AgentCore Runtime.

    Server side calls use SigV4 through boto3 (the backend's IAM role needs
    ``bedrock-agentcore:InvokeAgentRuntime``). The browser cannot set SigV4 headers on a
    WebSocket upgrade, so it receives a SigV4 PRE-SIGNED URL (60 seconds) pinned to the
    same runtime session (the role also needs
    ``bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream``).
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_interview_agentcore_arn:
            raise AgentUnavailableError("ORA_AI_INTERVIEW_AGENTCORE_ARN is not configured.")
        self._arn = settings.ai_interview_agentcore_arn
        self._region = settings.ai_interview_agentcore_region
        self._timeout = settings.ai_interview_agent_timeout_seconds

    def _invoke(self, body: dict[str, Any], runtime_session_id: str) -> dict[str, Any]:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError

        client = boto3.client(
            "bedrock-agentcore",
            region_name=self._region,
            config=Config(read_timeout=self._timeout, retries={"max_attempts": 2}),
        )
        try:
            response = client.invoke_agent_runtime(
                agentRuntimeArn=self._arn,
                runtimeSessionId=runtime_session_id,
                contentType="application/json",
                accept="application/json",
                payload=json.dumps(body).encode("utf-8"),
            )
            raw = response["response"].read()
        except (BotoCoreError, ClientError) as exc:
            raise AgentUnavailableError("The interview agent could not be reached.") from exc
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise AgentUnavailableError("The interview agent returned invalid JSON.") from exc
        if not isinstance(parsed, dict) or "error" in parsed:
            raise AgentUnavailableError("The interview agent rejected the request.")
        return parsed

    def plan_questions(
        self,
        *,
        interview_id: uuid.UUID,
        job_descriptions: list[dict[str, Any]],
        resume_text: str,
        candidate_ref: str,
        max_questions: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "action": "plan_questions",
            "interview_id": str(interview_id),
            "job_descriptions": job_descriptions,
            "resume": {"candidate_ref": candidate_ref, "text": resume_text},
        }
        if max_questions is not None:
            body["max_questions"] = max_questions
        return self._invoke(body, runtime_session_id_for(interview_id))

    def prepare_session(
        self,
        *,
        interview_id: uuid.UUID,
        question_set: dict[str, Any],
        role_title: str,
        consent_notice_version: str,
        runtime_session_id: str,
    ) -> str:
        parsed = self._invoke(
            {
                "action": "prepare_session",
                "interview_id": str(interview_id),
                "question_set": question_set,
                "role_title": role_title,
                "consent_notice_version": consent_notice_version,
                "consent_given": True,
            },
            runtime_session_id,
        )
        token = parsed.get("join_token")
        if not isinstance(token, str) or not token:
            raise AgentUnavailableError("The interview agent did not return a join token.")
        return token

    def connection_url(self, *, runtime_session_id: str) -> str:
        """SigV4 query-signed ``wss://`` URL for this runtime session only.

        Signed locally with botocore (no network call, no extra dependency). The expiry only
        has to cover opening the socket; an open interview keeps running after it. Security:
        the URL carries the signer's temporary session token, so it must not be logged.
        """
        import boto3
        from botocore.auth import SigV4QueryAuth
        from botocore.awsrequest import AWSRequest
        from botocore.exceptions import BotoCoreError

        host = f"bedrock-agentcore.{self._region}.amazonaws.com"
        url = (
            f"https://{host}/runtimes/{quote(self._arn, safe='')}/ws"
            f"?X-Amzn-Bedrock-AgentCore-Runtime-Session-Id={quote(runtime_session_id, safe='')}"
        )
        try:
            credentials = boto3.Session().get_credentials()
            if credentials is None:
                raise AgentUnavailableError("No AWS credentials available to sign the connection.")
            request = AWSRequest(method="GET", url=url, headers={"host": host})
            SigV4QueryAuth(
                credentials.get_frozen_credentials(),
                "bedrock-agentcore",
                self._region,
                expires=_WS_URL_TTL_SECONDS,
            ).add_auth(request)
        except BotoCoreError as exc:
            raise AgentUnavailableError("Could not create the interview connection.") from exc
        return str(request.url).replace("https://", "wss://", 1)


class FakeInterviewAgentClient:
    """Deterministic offline agent for tests. Never selectable in production."""

    def __init__(self) -> None:
        self.prepared: list[dict[str, Any]] = []

    def plan_questions(
        self,
        *,
        interview_id: uuid.UUID,
        job_descriptions: list[dict[str, Any]],
        resume_text: str,
        candidate_ref: str,
        max_questions: int | None = None,
    ) -> dict[str, Any]:
        title = job_descriptions[0]["title"] if job_descriptions else "the role"
        return {
            "interview_id": str(interview_id),
            "candidate_ref": candidate_ref,
            "version": "fake-v1",
            "generated_by": "deterministic_fallback",
            "model_id": None,
            "prompt_version": "fake",
            "approved": False,
            "questions": [
                {
                    "id": "q1",
                    "text": f"Tell me about your experience relevant to {title}.",
                    "competency": "general",
                    "source": "standard",
                    "evidence_ref": None,
                    "follow_up_allowed": True,
                },
                {
                    "id": "q2",
                    "text": "Describe a project you are proud of and your role in it.",
                    "competency": "general",
                    "source": "standard",
                    "evidence_ref": None,
                    "follow_up_allowed": True,
                },
            ],
        }

    def prepare_session(
        self,
        *,
        interview_id: uuid.UUID,
        question_set: dict[str, Any],
        role_title: str,
        consent_notice_version: str,
        runtime_session_id: str,
    ) -> str:
        # Mirror the real agent's contract checks so tests catch what production would reject.
        if not question_set.get("approved"):
            raise AgentUnavailableError("question_set_not_approved")
        if str(question_set.get("interview_id")) != str(interview_id):
            raise AgentUnavailableError("interview_mismatch")
        self.prepared.append(
            {"interview_id": str(interview_id), "runtime_session_id": runtime_session_id}
        )
        return "fake-join-token-0123456789"

    def connection_url(self, *, runtime_session_id: str) -> str:
        return "ws://fake-agent.invalid/ws"


def build_agent_client(settings: Settings) -> InterviewAgentClient:
    mode = settings.ai_interview_agent_mode
    if mode == "fake":
        return FakeInterviewAgentClient()
    if mode == "agentcore":
        return AgentCoreInterviewAgentClient(settings)
    return HttpInterviewAgentClient(settings)
