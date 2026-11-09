"""Local test broker for the deployed AgentCore interview agent. LOCAL TESTING ONLY.

It plays the role the HR backend (API Gateway + Lambda) will play in production:
  * holds AWS credentials (your AWS profile here; the Lambda IAM role in production),
  * calls InvokeAgentRuntime for plan_questions / prepare_session (SigV4),
  * creates a SigV4 pre-signed WebSocket URL that expires in 60 s and hands it to the browser.
The browser never receives AWS credentials; it connects to AgentCore directly with that URL.

Run (from interview-agent/):
  $env:AWS_PROFILE="OTL_GenAi"
  .venv\\Scripts\\python test-ui\\broker.py --runtime-arn <ARN>
Then open http://127.0.0.1:8090
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import boto3
import uvicorn
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SESSION_PARAM = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
WS_URL_TTL_SECONDS = 60  # only needs to cover opening the socket; the interview can run longer
PAGE = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

Text = Annotated[str, StringConstraints(min_length=1, max_length=20000)]


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    jd_text: Text
    skills: list[Annotated[str, StringConstraints(max_length=80)]] = Field(default_factory=list, max_length=30)
    resume_text: Text
    max_questions: int = Field(default=4, ge=1, le=10)


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_set: dict[str, Any]
    consent_given: bool


def create_app(runtime_arn: str, region: str) -> FastAPI:
    agentcore = boto3.client("bedrock-agentcore", region_name=region)
    session = boto3.Session()
    # interview_id -> runtime session id. prepare_session and the WebSocket must share it so
    # AgentCore routes both to the same isolated microVM.
    sessions: dict[str, str] = {}
    app = FastAPI(title="Interview agent test broker", docs_url=None, redoc_url=None, openapi_url=None)

    def invoke(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = agentcore.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            payload=json.dumps(payload).encode(),
            contentType="application/json",
            accept="application/json",
        )
        body = json.loads(resp["response"].read())
        if "error" in body:
            raise HTTPException(status_code=422, detail=body["error"].get("code", "agent_error"))
        return body

    def presign(session_id: str) -> str:
        host = f"bedrock-agentcore.{region}.amazonaws.com"
        url = f"https://{host}/runtimes/{quote(runtime_arn, safe='')}/ws?{SESSION_PARAM}={session_id}"
        creds = session.get_credentials().get_frozen_credentials()
        request = AWSRequest(method="GET", url=url, headers={"host": host})
        SigV4QueryAuth(creds, "bedrock-agentcore", region, expires=WS_URL_TTL_SECONDS).add_auth(request)
        return request.url.replace("https://", "wss://", 1)

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @app.post("/api/interviews")
    def start(req: StartRequest) -> dict[str, Any]:
        """HR step: draft questions from JD + resume (the agent's plan_questions)."""
        interview_id = str(uuid.uuid4())
        sessions[interview_id] = f"{uuid.uuid4()}-ui"  # >= 33 chars
        t0 = time.perf_counter()
        question_set = invoke(sessions[interview_id], {
            "action": "plan_questions",
            "interview_id": interview_id,
            "max_questions": req.max_questions,
            "job_descriptions": [{
                "jd_id": "jd-test", "title": req.role_title, "text": req.jd_text, "must_have_skills": req.skills,
            }],
            "resume": {"candidate_ref": "cand-test", "text": req.resume_text},
        })
        return {"interview_id": interview_id, "question_set": question_set, "seconds": round(time.perf_counter() - t0, 1)}

    @app.post("/api/interviews/{interview_id}/join")
    def join(interview_id: str, req: JoinRequest) -> dict[str, Any]:
        """Candidate step: prepare the session, then hand the browser a short-lived signed URL."""
        session_id = sessions.get(interview_id)
        if session_id is None:
            raise HTTPException(status_code=404, detail="unknown_interview")
        question_set = dict(req.question_set)
        question_set["approved"], question_set["approved_by"] = True, "test-ui"  # HR approval in the real app
        prepared = invoke(session_id, {
            "action": "prepare_session",
            "interview_id": interview_id,
            "question_set": question_set,
            "role_title": "Test interview",
            "consent_notice_version": "test-ui",
            "consent_given": req.consent_given,
        })
        return {
            "ws_url": presign(session_id),
            "join_token": prepared["join_token"],
            "expires_in": WS_URL_TTL_SECONDS,
        }

    @app.post("/api/interviews/{interview_id}/stop")
    def stop(interview_id: str) -> dict[str, str]:
        """Frees the runtime microVM right away instead of waiting for the idle timeout."""
        session_id = sessions.pop(interview_id, None)
        if session_id:
            agentcore.stop_runtime_session(agentRuntimeArn=runtime_arn, runtimeSessionId=session_id, qualifier="DEFAULT")
        return {"status": "stopped"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    # Bound to localhost only: this broker holds your AWS credentials.
    uvicorn.run(create_app(args.runtime_arn, args.region), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
