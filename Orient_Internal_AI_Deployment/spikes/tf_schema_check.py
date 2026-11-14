"""Check that the pinned AWS provider supports what the chatbot Terraform needs."""

from __future__ import annotations

import json
import os
import pathlib

raw = pathlib.Path(os.environ["TEMP"], "tf-schema.json").read_bytes()
print("first bytes:", raw[:60])
data = json.loads(raw[raw.index(b"{"):].decode("utf-8", errors="replace"))
aws = next(v for k, v in data["provider_schemas"].items() if k.endswith("hashicorp/aws"))
res = aws["resource_schemas"]
for name in ("aws_s3vectors_vector_bucket", "aws_s3vectors_index", "aws_bedrockagent_knowledge_base",
             "aws_bedrockagent_data_source", "aws_bedrock_guardrail", "aws_bedrock_guardrail_version",
             "aws_scheduler_schedule", "aws_kms_key"):
    print(f"{name}: {'YES' if name in res else 'NO'}")


def blocks(schema: dict, path: list[str]) -> dict:
    node = schema["block"]
    for p in path:
        node = node["block_types"][p]["block"]
    return node


kb = res.get("aws_bedrockagent_knowledge_base")
if kb:
    storage = blocks(kb, ["storage_configuration"])
    print("KB storage blocks:", sorted(storage.get("block_types", {})))
    if "s3_vectors_configuration" in storage.get("block_types", {}):
        print("  s3_vectors_configuration attrs:",
              sorted(blocks(kb, ["storage_configuration", "s3_vectors_configuration"])["attributes"]))
idx = res.get("aws_s3vectors_index")
if idx:
    print("index attrs:", sorted(idx["block"]["attributes"]), sorted(idx["block"].get("block_types", {})))
