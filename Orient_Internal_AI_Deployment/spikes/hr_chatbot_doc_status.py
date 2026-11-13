"""Print per-document ingestion status for the spike KB (read-only)."""

from __future__ import annotations

import json
import pathlib

import boto3

state = json.loads((pathlib.Path(__file__).parent / "hr_chatbot_kb_spike_state.json").read_text())
agent = boto3.Session(profile_name="Orient_Internal_AI", region_name="ap-south-1").client("bedrock-agent")
print("job failureReasons:", state.get("ingestion", {}).get("failure_reasons"))
docs = agent.list_knowledge_base_documents(knowledgeBaseId=state["kb_id"], dataSourceId=state["ds_id"])
for d in docs["documentDetails"]:
    uri = d.get("identifier", {}).get("s3", {}).get("uri", "")
    print(d.get("status"), uri.split("/", 3)[-1], "|", (d.get("statusReason") or "")[:400])
