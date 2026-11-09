"""Where finished interview records go: local file (dev), S3, and a signed webhook to the HR platform."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .models import InterviewRecord
from .ports import ResultSink

log = logging.getLogger(__name__)


class PersistenceError(RuntimeError):
    pass


class LocalFileSink:
    """Development only. File name comes from a UUID, never from user text."""

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)

    def persist(self, record: InterviewRecord) -> str:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{record.summary.interview_id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return str(path)


class S3ResultSink:
    """Server-side encrypted object. Bucket must block public access (checked in deployment docs)."""

    def __init__(self, bucket: str, prefix: str, region: str, client: Any | None = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    def persist(self, record: InterviewRecord) -> str:
        key = f"{self._prefix}{record.summary.interview_id}.json"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=record.model_dump_json().encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        return f"s3://{self._bucket}/{key}"


class WebhookSink:
    """POSTs the record to the HR platform. HMAC-SHA256 over `timestamp.body`; idempotent by id."""

    def __init__(self, url: str, secret: str, *, attempts: int = 3) -> None:
        self._url = url
        self._secret = secret.encode()
        self._attempts = attempts

    def persist(self, record: InterviewRecord) -> str:
        import httpx

        body = record.model_dump_json().encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(self._secret, timestamp.encode() + b"." + body, hashlib.sha256)
        headers = {
            "Content-Type": "application/json",
            "X-Interview-Timestamp": timestamp,
            "X-Interview-Signature": signature.hexdigest(),
            "Idempotency-Key": str(record.summary.interview_id),
        }
        last_error = "unknown"
        for attempt in range(1, self._attempts + 1):
            try:
                response = httpx.post(self._url, content=body, headers=headers, timeout=10.0)
                if response.status_code < 300:
                    return self._url
                last_error = f"http_{response.status_code}"
                if response.status_code < 500:
                    break  # client error will not succeed on retry
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            time.sleep(min(2**attempt, 8))
        raise PersistenceError(f"webhook_failed:{last_error}")


class CompositeSink:
    """Tries every sink. Succeeds if at least one stored the record."""

    def __init__(self, sinks: list[ResultSink]) -> None:
        self._sinks = sinks

    def persist(self, record: InterviewRecord) -> str:
        locations: list[str] = []
        for sink in self._sinks:
            try:
                locations.append(sink.persist(record))
            except Exception as exc:  # noqa: BLE001 - recorded, and we fail if nothing succeeded
                log.error(
                    "sink_failed",
                    extra={
                        "sink": type(sink).__name__,
                        "error": type(exc).__name__,
                        "interview_id": str(record.summary.interview_id),
                    },
                )
        if not locations:
            raise PersistenceError("all_sinks_failed")
        return ",".join(locations)


def build_sink(settings: Settings) -> ResultSink:
    sinks: list[ResultSink] = []
    if settings.s3_bucket:
        sinks.append(S3ResultSink(settings.s3_bucket, settings.s3_prefix, settings.aws_region))
    if settings.webhook_url and settings.webhook_secret:
        sinks.append(WebhookSink(settings.webhook_url, settings.webhook_secret.get_secret_value()))
    if settings.environment == "local" or not sinks:
        sinks.append(LocalFileSink(settings.output_dir))
    return CompositeSink(sinks)
