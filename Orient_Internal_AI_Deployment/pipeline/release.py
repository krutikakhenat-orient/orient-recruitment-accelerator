"""Deploy stage of the backend release pipeline (CodeBuild). Runs from the Build artifact.

Releases Lambda CODE only (infrastructure is Terraform, applied locally). Order:
  1. upload lambda.zip to s3://APP_ARTIFACT_BUCKET/releases/<commit>/lambda.zip
  2. update the code of the ops and api functions, verify the SHA-256, publish version N of each
  3. snapshot the Aurora cluster if the release adds migrations (backup before schema change)
  4. migrate the database with ops version N
  5. test api version N directly (synthetic GET /health)        <- live traffic still on N-1
  6. point the `live` alias (API Gateway's target) to api version N
  7. public smoke test through API Gateway
  8. on smoke-test failure: point `live` back to N-1 and fail the release
  9. record the released commit (Build diffs the next release against it)

Migrations must keep version N-1 working (expand/contract, see docs/backend-cicd-pipeline.md):
after step 4 the old code may keep serving, and a rollback in step 8 only moves the alias.

Environment: API_FUNCTION, OPS_FUNCTION, API_ALIAS, APP_ARTIFACT_BUCKET, DB_CLUSTER_ID, API_URL,
RELEASE_PARAM, SNAPSHOT_TAGS (JSON list of {Key, Value}).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SMOKE_CHECKS: tuple[tuple[str, int], ...] = (
    ("/health", 200),
    ("/api/v1/auth/me", 401),  # routing + app + auth layer answer; no credentials needed
)
SMOKE_ATTEMPTS = 6
SMOKE_DELAY_SECONDS = 10


def log(msg: str) -> None:
    print(f"[release] {msg}", flush=True)


def health_event() -> dict[str, Any]:
    """Minimal API Gateway HTTP API (payload v2.0) event for GET /health."""
    now = dt.datetime.now(dt.UTC)
    return {
        "version": "2.0",
        "routeKey": "ANY /{proxy+}",
        "rawPath": "/health",
        "rawQueryString": "",
        "headers": {
            "host": "release-check.internal",
            "user-agent": "ora-release-check",
            "x-forwarded-proto": "https",
            "x-forwarded-port": "443",
        },
        "requestContext": {
            "accountId": "release-check",
            "apiId": "release-check",
            "domainName": "release-check.internal",
            "domainPrefix": "release-check",
            "http": {
                "method": "GET",
                "path": "/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "ora-release-check",
            },
            "requestId": f"release-check-{int(now.timestamp())}",
            "routeKey": "ANY /{proxy+}",
            "stage": "$default",
            "time": now.strftime("%d/%b/%Y:%H:%M:%S +0000"),
            "timeEpoch": int(now.timestamp() * 1000),
        },
        "isBase64Encoded": False,
    }


def snapshot_id(commit_short: str, now: dt.datetime) -> str:
    return f"ora-pre-{commit_short}-{now:%Y%m%d%H%M}"


def http_status(url: str) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "ora-release-smoke"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https URL)
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return 0


def smoke_ok(api_url: str) -> bool:
    for attempt in range(1, SMOKE_ATTEMPTS + 1):
        results = [
            (path, want, http_status(api_url.rstrip("/") + path)) for path, want in SMOKE_CHECKS
        ]
        detail = ", ".join(f"{p}={got} (want {w})" for p, w, got in results)
        log(f"smoke attempt {attempt}: {detail}")
        if all(got == want for _, want, got in results):
            return True
        time.sleep(SMOKE_DELAY_SECONDS)
    return False


class Releaser:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.api_fn = os.environ["API_FUNCTION"]
        self.ops_fn = os.environ["OPS_FUNCTION"]
        self.alias = os.environ["API_ALIAS"]
        self.bucket = os.environ["APP_ARTIFACT_BUCKET"]
        self.cluster = os.environ["DB_CLUSTER_ID"]
        self.api_url = os.environ["API_URL"]
        self.param = os.environ["RELEASE_PARAM"]
        self.tags = json.loads(os.environ.get("SNAPSHOT_TAGS", "[]"))
        # Migrations can run for minutes: allow the full 15-minute Lambda timeout.
        self.lam = boto3.client(
            "lambda",
            config=Config(read_timeout=900, connect_timeout=10, retries={"max_attempts": 2}),
        )
        self.s3 = boto3.client("s3")
        self.rds = boto3.client("rds")
        self.ssm = boto3.client("ssm")

    def invoke(self, fn: str, qualifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self.lam.invoke(
            FunctionName=fn, Qualifier=qualifier, Payload=json.dumps(payload).encode()
        )
        body = resp["Payload"].read().decode()
        if resp.get("FunctionError"):
            raise RuntimeError(f"{fn}:{qualifier} returned an error: {body[:2000]}")
        result: dict[str, Any] = json.loads(body)
        return result

    def publish(self, fn: str, key: str, sha_b64: str, short: str) -> str:
        waiter = self.lam.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=fn)  # no update already in progress
        self.lam.update_function_code(FunctionName=fn, S3Bucket=self.bucket, S3Key=key)
        waiter.wait(FunctionName=fn)
        actual = self.lam.get_function_configuration(FunctionName=fn)["CodeSha256"]
        if actual != sha_b64:
            raise RuntimeError(f"{fn}: deployed code SHA {actual} != built {sha_b64}")
        # CodeSha256 makes the publish fail if $LATEST changed in between.
        version = self.lam.publish_version(
            FunctionName=fn, CodeSha256=sha_b64, Description=f"commit {short}"
        )["Version"]
        self.lam.get_waiter("published_version_active").wait(FunctionName=fn, Qualifier=version)
        log(f"{fn}: published version {version}")
        return str(version)

    def snapshot(self, short: str) -> None:
        sid = snapshot_id(short, dt.datetime.now(dt.UTC))
        log(f"creating cluster snapshot {sid} before migrations")
        self.rds.create_db_cluster_snapshot(
            DBClusterSnapshotIdentifier=sid, DBClusterIdentifier=self.cluster, Tags=self.tags
        )
        self.rds.get_waiter("db_cluster_snapshot_available").wait(
            DBClusterSnapshotIdentifier=sid, WaiterConfig={"Delay": 20, "MaxAttempts": 90}
        )
        log(f"snapshot {sid} available")

    def run(self, release: dict[str, Any]) -> int:
        if not release.get("backend_changed"):
            log("no backend change in this commit; nothing to release")
            return 0
        commit = str(release["commit"])
        short = str(release["commit_short"])
        sha_b64 = str(release["zip_sha256_b64"])
        key = f"releases/{commit}/lambda.zip"

        log(f"releasing {short}: {release.get('summary', '')}")
        self.s3.upload_file("lambda.zip", self.bucket, key)
        log(f"uploaded s3://{self.bucket}/{key}")

        ops_version = self.publish(self.ops_fn, key, sha_b64, short)
        api_version = self.publish(self.api_fn, key, sha_b64, short)

        if release.get("has_migrations"):
            self.snapshot(short)
        result = self.invoke(self.ops_fn, ops_version, {"action": "migrate"})
        if result.get("status") != "ok":
            raise RuntimeError(f"migration failed: {result}")
        log(f"migrate: {result.get('result')}")

        check = self.invoke(self.api_fn, api_version, health_event())
        if check.get("statusCode") != 200:
            raise RuntimeError(f"api version {api_version} failed its health check: {check}")
        log(f"api version {api_version} answered /health with 200 (live traffic not switched yet)")

        previous = str(
            self.lam.get_alias(FunctionName=self.api_fn, Name=self.alias)["FunctionVersion"]
        )
        self.lam.update_alias(
            FunctionName=self.api_fn,
            Name=self.alias,
            FunctionVersion=api_version,
            Description=f"commit {short}",
        )
        log(f"alias {self.alias}: {previous} -> {api_version}")

        if not smoke_ok(self.api_url):
            if previous not in ("", "$LATEST", api_version):
                self.lam.update_alias(
                    FunctionName=self.api_fn,
                    Name=self.alias,
                    FunctionVersion=previous,
                    Description="rolled back by release pipeline",
                )
                log(f"ROLLED BACK: alias {self.alias} -> {previous}")
            else:
                log(f"cannot roll back automatically: previous alias target was {previous!r}")
            log("release FAILED at the public smoke test")
            return 1

        self.ssm.put_parameter(Name=self.param, Value=commit, Overwrite=True)
        log(
            f"released {short}: api v{api_version}, ops v{ops_version}; "
            f"rollback: aws lambda update-alias --function-name {self.api_fn} "
            f"--name {self.alias} --function-version {previous}"
        )
        return 0


def main() -> int:
    release = json.loads(Path("release.json").read_text())
    return Releaser().run(release)


if __name__ == "__main__":
    sys.exit(main())
