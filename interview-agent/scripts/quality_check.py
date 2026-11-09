"""Dummy-candidate test of the full HR-app -> AgentCore voice interview, plus a quality report.

SYNTHETIC DATA ONLY. Local HR app (http://localhost:8000) running in agentcore mode.

  prepare   HR side via the API: draft (if needed) -> plan questions -> approve; prints the
            single-use candidate link. You then open it and do the interview by voice.
  report    Pulls the finished record from the S3 results bucket, delivers it to the local
            HR backend's webhook exactly like the agent would (HMAC-signed), so the summary
            appears in the UI, and prints a quality report.

Usage (from interview-agent/, AWS_PROFILE=OTL_GenAi):
  .venv\\Scripts\\python scripts\\quality_check.py prepare
  .venv\\Scripts\\python scripts\\quality_check.py report --interview-id <id>
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import re
import statistics
import sys
import time
from pathlib import Path

import boto3
import httpx

API = "http://localhost:8000"
CAMPAIGN = "efaac180-6272-4a51-99db-75ea6f8b20f8"  # SYNTHETIC hook campaign
BUCKET = "agentcore-interviewagent--interviewresultsdebf34ed-g1rqjiuuayll"
SECRET_FILE = Path(__file__).resolve().parents[2] / "backend" / ".env.ai-interview.local"
LOGIN = {"email": "synthetic.recruiter_admin@example.com", "password": "SyntheticDevPassword123"}


def staff_client() -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=120)
    c.headers["Authorization"] = "Bearer " + c.post("/api/v1/auth/login", json=LOGIN).json()["access_token"]
    return c


def prepare() -> None:
    c = staff_client()
    sessions = c.get(f"/api/v1/ai-interviews/campaigns/{CAMPAIGN}/sessions").json()
    row = next((s for s in sessions if s["status"] in ("pending_plan", "questions_ready", "approved")), None)
    if row is None:
        app_id = sessions[0]["application_id"] if sessions else sys.exit("No application found.")
        row = c.post(f"/api/v1/ai-interviews/applications/{app_id}").json()
    sid = row["id"]
    if row["status"] == "pending_plan":
        t0 = time.perf_counter()
        planned = c.post(f"/api/v1/ai-interviews/sessions/{sid}/plan")
        planned.raise_for_status()
        row = planned.json()
        print(f"Questions drafted by {row['generated_by']} in {time.perf_counter() - t0:.1f}s:")
    for i, q in enumerate(row["questions"], 1):
        print(f"  {i:2}. [{q['competency']}] {q['text']}")
    if row["status"] == "approved":
        # Already approved (link lost): issue a fresh link; the previous one stops working.
        approved = c.post(f"/api/v1/ai-interviews/sessions/{sid}/link")
    else:
        approved = c.post(f"/api/v1/ai-interviews/sessions/{sid}/approve", json={"reason": "quality test"})
    approved.raise_for_status()
    print("\nApproved. Candidate link (single use, shown once):")
    print(f"  {approved.json()['link_url']}")
    print(f"\nInterview id: {sid}")
    print("After the interview run:")
    print(f"  .venv\\Scripts\\python scripts\\quality_check.py report --interview-id {sid}")


def _secret() -> str:
    for line in SECRET_FILE.read_text("utf-8").splitlines():
        if line.startswith("ORA_AI_INTERVIEW_WEBHOOK_SECRET="):
            return line.split("=", 1)[1].strip()
    sys.exit("Webhook secret not found in backend/.env.ai-interview.local")


def _deliver(body: bytes) -> str:
    """Same signature scheme as the agent's WebhookSink: HMAC-SHA256 over 'timestamp.body'."""
    ts = str(int(time.time()))
    sig = hmac.new(_secret().encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    r = httpx.post(f"{API}/api/v1/ai-interviews/webhook", content=body, timeout=30, headers={
        "Content-Type": "application/json", "X-Interview-Timestamp": ts, "X-Interview-Signature": sig})
    return f"{r.status_code} {r.text[:120]}"


def _at(turn: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(turn["at"].replace("Z", "+00:00"))


def report(interview_id: str) -> None:
    s3 = boto3.client("s3", region_name="ap-south-1")
    key = f"interviews/{interview_id}.json"
    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey:
        sys.exit(f"No record yet at s3://{BUCKET}/{key} (interview not finished?)")
    record = json.loads(body)
    summary, turns = record["summary"], record["transcript"]
    print(f"Webhook delivery to local HR app: {_deliver(body)}\n")

    agent = [t for t in turns if t["speaker"] == "agent"]
    cand = [t for t in turns if t["speaker"] == "candidate"]
    words = [len(t["text"].split()) for t in cand]
    # Time from the candidate's finished utterance being recorded to the agent's reply text being
    # ready. Covers the LLM follow-up call; excludes end-of-speech wait, TTS and network.
    gaps = []
    for i, t in enumerate(turns[:-1]):
        if t["speaker"] == "candidate" and turns[i + 1]["speaker"] == "agent":
            gaps.append((_at(turns[i + 1]) - _at(t)).total_seconds())
    approved_q = {a["question_id"]: a for a in summary["assessments"]}
    asked_q = {t["question_id"] for t in agent if t.get("question_id")}
    followups = [t for t in agent if t["text"].endswith("?") and t["question_id"]
                 and t["text"] != approved_q.get(t["question_id"], {}).get("question_text")]
    verdict = re.compile(r"\b(unfit|bad candidate|reject|hire|score|rating)\b", re.I)

    print("== Session ==")
    print(f"  end_reason={summary['end_reason']}  duration={summary['duration_seconds']}s  "
          f"summary_by={summary['generated_by']} ({summary.get('model_id')})")
    print(f"  turns: agent={len(agent)} candidate={len(cand)}  follow-ups asked={len(followups)}")
    print(f"  questions reached: {len(asked_q & approved_q.keys())}/{len(approved_q)}")
    print("\n== Responsiveness (reply text ready after your utterance) ==")
    if gaps:
        print(f"  median={statistics.median(gaps):.2f}s  max={max(gaps):.2f}s  n={len(gaps)}"
              "  (+ ~0.8s end-of-speech wait + TTS start ~0.4-1.3s, not measured here)")
    print("\n== Your answers as transcribed (compare with what you actually said) ==")
    for t in cand:
        flag = f"  FLAGS={t['flags']}" if t.get("flags") else ""
        print(f"  - {t['text']}{flag}")
    if words:
        print(f"  words per answer: median={statistics.median(words)} min={min(words)} max={max(words)}")
    print("\n== Summary quality ==")
    print(f"  overview: {summary['overview']}")
    for a in summary["assessments"]:
        review = f"  REVIEW: {a['review_reason']}" if a["needs_human_review"] else ""
        print(f"  [{a['coverage']:18}] {a['question_text'][:70]}")
        print(f"      summary: {a['answer_summary'][:160]}")
        if a["evidence_quotes"]:
            print(f"      quotes: {a['evidence_quotes']}")
        if review:
            print(f"     {review}")
    print(f"  topics to probe next: {summary['topics_to_probe_next']}")
    print(f"  integrity flags: {summary['integrity_flags'] or 'none'}")
    all_text = summary["overview"] + " " + " ".join(a["answer_summary"] for a in summary["assessments"])
    print(f"  verdict/score language in summary: {'FOUND' if verdict.search(all_text) else 'none'}")
    print("\nOpen the campaign in the HR app to see the result in the AI voice interviews panel.")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    rep = sub.add_parser("report")
    rep.add_argument("--interview-id", required=True)
    args = parser.parse_args()
    prepare() if args.cmd == "prepare" else report(args.interview_id)


if __name__ == "__main__":
    main()
