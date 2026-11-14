"""Read-only probe for the HR chatbot Phase 0 trial (creates nothing).

Usage: python hr_chatbot_probe.py   (uses AWS profile Orient_Internal_AI, ap-south-1)
"""

from __future__ import annotations

import boto3
import botocore

PROFILE, REGION = "Orient_Internal_AI", "ap-south-1"
session = boto3.Session(profile_name=PROFILE, region_name=REGION)
print("botocore", botocore.__version__)

bedrock = session.client("bedrock")
wanted = ("titan-embed-text-v2", "nova-lite", "nova-micro", "nova-pro", "haiku", "cohere.embed")
for m in bedrock.list_foundation_models()["modelSummaries"]:
    if any(w in m["modelId"] for w in wanted):
        print("model", m["modelId"], m.get("inferenceTypesSupported"),
              m.get("modelLifecycle", {}).get("status"))

for p in bedrock.list_inference_profiles(maxResults=1000)["inferenceProfileSummaries"]:
    if any(w in p["inferenceProfileId"] for w in ("nova", "haiku")):
        regions = sorted({m["modelArn"].split(":")[3] for m in p.get("models", [])})
        print("profile", p["inferenceProfileId"], "->", regions)

agent_model = session.client("bedrock-agent").meta.service_model
storage = agent_model.shape_for("StorageConfiguration")
print("KB storage types:", storage.members["type"].enum)

print("guardrails:", len(bedrock.list_guardrails()["guardrails"]))
print("existing KBs:", [k["name"] for k in session.client("bedrock-agent").list_knowledge_bases()["knowledgeBaseSummaries"]])
