"""Confirm the spike left nothing behind (read-only)."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

s = boto3.Session(profile_name="Orient_Internal_AI", region_name="ap-south-1")
acct = s.client("sts").get_caller_identity()["Account"]
print("KBs:", [k["name"] for k in s.client("bedrock-agent").list_knowledge_bases()["knowledgeBaseSummaries"]])
print("guardrails:", [g["name"] for g in s.client("bedrock").list_guardrails()["guardrails"]])
print("vector buckets:", [b["vectorBucketName"] for b in s.client("s3vectors").list_vector_buckets()["vectorBuckets"]])
try:
    s.client("s3").head_bucket(Bucket=f"ora-kbspike-docs-{acct}")
    print("docs bucket: STILL EXISTS")
except ClientError as exc:
    print("docs bucket:", exc.response["Error"]["Code"])
try:
    s.client("iam").get_role(RoleName="ora-kbspike-kb-role")
    print("role: STILL EXISTS")
except ClientError as exc:
    print("role:", exc.response["Error"]["Code"])
