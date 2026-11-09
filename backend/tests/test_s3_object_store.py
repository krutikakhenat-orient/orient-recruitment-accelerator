"""S3 object store: signed-link format (offline - presigning makes no network call)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.documents.storage import S3ObjectStore


def test_presigned_url_is_regional_sigv4(monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic, non-secret test credentials: presigning is a local computation.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIASYNTHETICTEST000")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-test-secret-not-real")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")

    store = S3ObjectStore("synthetic-test-bucket")
    url = store.presigned_get_url("induction/org/video.mp4", "video/mp4", 600)

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    # Regional virtual-hosted host (not the global s3.amazonaws.com endpoint).
    assert parsed.hostname == "synthetic-test-bucket.s3.ap-south-1.amazonaws.com"
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["600"]
    assert query["response-content-type"] == ["video/mp4"]
    assert "ap-south-1" in query["X-Amz-Credential"][0]
