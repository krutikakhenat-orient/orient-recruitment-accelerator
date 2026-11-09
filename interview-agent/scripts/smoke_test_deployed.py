"""Smoke test against the DEPLOYED AgentCore runtime, using the same path the HR backend will use.

1. InvokeAgentRuntime {plan_questions}   (SigV4, caller's IAM identity)
2. InvokeAgentRuntime {prepare_session}  (same runtime session id S)
3. WebSocket via a SigV4 pre-signed URL for session S (what the browser will receive)
4. Typed answers until the interview ends; confirm the record was written to S3.

SYNTHETIC DATA ONLY.  Usage (from interview-agent/):
  $env:AWS_PROFILE="OTL_GenAi"
  .venv\\Scripts\\python scripts\\smoke_test_deployed.py --runtime-arn <ARN> --bucket <results bucket>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from urllib.parse import quote

import boto3
import websockets
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest

REGION = "ap-south-1"
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


def invoke(client, arn: str, session_id: str, payload: dict) -> dict:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode(),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(resp["response"].read())
    print(f"  {payload['action']}: {time.perf_counter() - started:.1f}s")
    return body


def presigned_ws_url(arn: str, session_id: str, expires: int = 60) -> str:
    """Same thing the HR backend Lambda will do: sign locally, hand the URL to the browser."""
    host = f"bedrock-agentcore.{REGION}.amazonaws.com"
    url = f"https://{host}/runtimes/{quote(arn, safe='')}/ws?{SESSION_HEADER}={session_id}"
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    request = AWSRequest(method="GET", url=url, headers={"host": host})
    SigV4QueryAuth(credentials, "bedrock-agentcore", REGION, expires=expires).add_auth(request)
    return request.url.replace("https://", "wss://", 1)


async def interview(ws_url: str, interview_id: str, join_token: str) -> None:
    answer = (
        "In my last synthetic project I designed a REST API in Python with FastAPI, "
        "modelled the PostgreSQL schema, wrote the tests and deployed it on AWS Lambda myself."
    )
    audio_bytes = 0
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "interview_id": interview_id, "join_token": join_token}))
        async for message in ws:
            if isinstance(message, bytes):
                audio_bytes += len(message)
                continue
            data = json.loads(message)
            kind = data["type"]
            if kind == "agent_text":
                print(f"  AGENT: {data['text'][:100]}")
            elif kind in ("ready", "warning", "error", "ended"):
                print(f"  [{kind}] {data.get('code') or data.get('reason') or ''}")
            if kind == "agent_audio_end":
                await ws.send(json.dumps({"type": "utterance", "text": answer}))
            if kind in ("ended", "error"):
                break
    print(f"  agent audio received: {audio_bytes / 32000:.1f} s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--bucket", required=True)
    args = parser.parse_args()

    client = boto3.client("bedrock-agentcore", region_name=REGION)
    session_id = str(uuid.uuid4()) + "-smoke"  # >= 33 characters
    interview_id = str(uuid.uuid4())

    print("1. plan questions")
    qs = invoke(client, args.runtime_arn, session_id, {
        "action": "plan_questions",
        "interview_id": interview_id,
        "max_questions": 2,
        "job_descriptions": [{
            "jd_id": "jd-smoke", "title": "Synthetic Backend Engineer",
            "text": "Build REST APIs in Python with FastAPI and PostgreSQL on AWS.",
            "must_have_skills": ["Python", "PostgreSQL"],
        }],
        "resume": {"candidate_ref": "cand-smoke", "text": "SYNTHETIC RESUME. Python, FastAPI, PostgreSQL, AWS Lambda."},
    })
    print(f"  generated_by={qs.get('generated_by')} questions={len(qs.get('questions', []))}")
    qs["approved"], qs["approved_by"] = True, "smoke-test"  # HR approval happens in the HR app

    print("2. prepare session")
    prep = invoke(client, args.runtime_arn, session_id, {
        "action": "prepare_session", "interview_id": interview_id, "question_set": qs,
        "role_title": "Synthetic Backend Engineer", "consent_notice_version": "smoke", "consent_given": True,
    })

    print("3. websocket interview (pre-signed URL)")
    asyncio.run(interview(presigned_ws_url(args.runtime_arn, session_id), interview_id, prep["join_token"]))

    print("4. result in S3")
    s3 = boto3.client("s3", region_name=REGION)
    key = f"interviews/{interview_id}.json"
    for _ in range(20):
        try:
            record = json.loads(s3.get_object(Bucket=args.bucket, Key=key)["Body"].read())
            summary = record["summary"]
            print(f"  s3://{args.bucket}/{key}")
            print(f"  end_reason={summary['end_reason']} generated_by={summary['generated_by']} turns={len(record['transcript'])}")
            break
        except s3.exceptions.NoSuchKey:
            time.sleep(1.5)
    else:
        print("  NOT FOUND")

    client.stop_runtime_session(agentRuntimeArn=args.runtime_arn, runtimeSessionId=session_id, qualifier="DEFAULT")
    print("session stopped")


if __name__ == "__main__":
    main()
