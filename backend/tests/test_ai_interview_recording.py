# ruff: noqa: F811 - pytest fixtures imported from test_ai_interviews are re-used by name
"""AI interview video evidence: consent, upload safety, access control, audit, retention.

All data is SYNTHETIC. The "video" is a few fake bytes behind a real WebM header; nothing in
the platform decodes or analyses it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.deps import settings_dep
from app.modules.ai_interviews import recording
from app.modules.ai_interviews import service as ai_service
from app.modules.ai_interviews.models import AiInterviewRecording, RecordingStatus
from app.modules.ai_interviews.router import get_object_store
from app.modules.audit.models import AuditEvent
from app.modules.documents.storage import InMemoryObjectStore
from app.modules.identity.models import Role
from app.modules.identity.permissions import RoleName
from tests.factories import make_user
from tests.test_ai_interviews import (  # noqa: F401 - pytest fixtures
    _enabled_settings,
    _to_approved,
    agent,
    world,
)
from tests.test_check_in_out_api import PASSWORD, _login

BASE = "/api/v1/ai-interviews"
WEBM_HEADER = b"\x1a\x45\xdf\xa3"
CHUNK_0 = WEBM_HEADER + b"SYNTHETIC-video-part-0"
CHUNK_1 = b"SYNTHETIC-video-part-1"


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def video_world(client, world, store):  # type: ignore[no-untyped-def]
    settings = _enabled_settings(ai_interview_video_enabled=True)
    client.app.dependency_overrides[settings_dep] = lambda: settings
    client.app.dependency_overrides[get_object_store] = lambda: store
    return {**world, "settings": settings}


def _start(client, token: str, *, video: bool) -> Any:  # type: ignore[no-untyped-def]
    body: dict[str, Any] = {
        "token": token,
        "consent": True,
        "notice_version": ai_service.NOTICE_VERSION,
    }
    if video:
        body |= {"video_consent": True, "video_notice_version": recording.VIDEO_NOTICE_VERSION}
    return client.post(f"{BASE}/public/start", json=body)


def _chunk(client, rec_token: str, seq: int, data: bytes, ctype: str = "video/webm"):  # type: ignore[no-untyped-def]
    return client.post(
        f"{BASE}/public/recording/chunk",
        params={"seq": seq},
        content=data,
        headers={"X-Recording-Token": rec_token, "Content-Type": ctype},
    )


def _recorded(client, video_world) -> tuple[dict[str, str], str, str]:  # type: ignore[no-untyped-def]
    """Admin headers, session id, upload token for an interview that is being recorded."""
    headers, sid, token, _ = _to_approved(client, video_world)
    started = _start(client, token, video=True)
    assert started.status_code == 200, started.text
    rec_token = started.json()["recording_token"]
    assert rec_token
    return headers, sid, rec_token


def _audit_actions(engine) -> list[str]:  # type: ignore[no-untyped-def]
    factory = sessionmaker(bind=engine, future=True)
    with factory() as db:
        return list(db.execute(select(AuditEvent.action)).scalars())


# ------------------------------------------------------------------ consent and offer


def test_video_is_not_offered_when_the_feature_is_off(client, world) -> None:  # type: ignore[no-untyped-def]
    _, _, token, _ = _to_approved(client, world)
    preview = client.post(f"{BASE}/public/preview", json={"token": token}).json()
    assert preview["video_recording_offered"] is False
    assert preview["video_notice_text"] is None
    # Even if a client sends video consent, nothing is recorded while the feature is off.
    started = _start(client, token, video=True)
    assert started.status_code == 200
    assert started.json()["recording_token"] is None


def test_video_is_offered_with_its_own_notice(client, video_world) -> None:  # type: ignore[no-untyped-def]
    _, _, token, _ = _to_approved(client, video_world)
    preview = client.post(f"{BASE}/public/preview", json={"token": token}).json()
    assert preview["video_recording_offered"] is True
    assert preview["video_notice_version"] == recording.VIDEO_NOTICE_VERSION
    assert "never analysed" in preview["video_notice_text"]
    assert "30 days" in preview["video_notice_text"]


def test_declining_video_still_starts_the_voice_interview(client, video_world) -> None:  # type: ignore[no-untyped-def]
    _, _, token, _ = _to_approved(client, video_world)
    started = _start(client, token, video=False)
    assert started.status_code == 200
    assert started.json()["recording_token"] is None
    assert started.json()["join_token"]


def test_a_stale_video_notice_is_rejected(client, video_world) -> None:  # type: ignore[no-untyped-def]
    _, _, token, _ = _to_approved(client, video_world)
    resp = client.post(
        f"{BASE}/public/start",
        json={
            "token": token, "consent": True, "notice_version": ai_service.NOTICE_VERSION,
            "video_consent": True, "video_notice_version": "old-video-notice",
        },
    )
    assert resp.status_code == 422


# ------------------------------------------------------------------ upload safety


def test_upload_rules(client, video_world) -> None:  # type: ignore[no-untyped-def]
    _, _, rec_token = _recorded(client, video_world)
    # The first chunk must be a video file.
    assert _chunk(client, rec_token, 0, b"MZ-not-a-video").status_code == 422
    assert _chunk(client, rec_token, 0, CHUNK_0, ctype="text/html").status_code == 422
    # Size limit.
    too_big = WEBM_HEADER + b"x" * video_world["settings"].ai_interview_video_max_chunk_bytes
    assert _chunk(client, rec_token, 0, too_big).status_code == 422
    # A wrong token reveals nothing.
    assert _chunk(client, "x" * 40, 0, CHUNK_0).status_code == 404
    assert _chunk(client, rec_token, 0, CHUNK_0).status_code == 200
    # The format cannot change mid-recording.
    assert _chunk(client, rec_token, 1, CHUNK_1, ctype="video/mp4").status_code == 422
    ok = _chunk(client, rec_token, 1, CHUNK_1)
    assert ok.status_code == 200 and ok.json()["chunk_count"] == 2


def test_finishing_kills_the_upload_token(client, video_world) -> None:  # type: ignore[no-untyped-def]
    _, _, rec_token = _recorded(client, video_world)
    assert _chunk(client, rec_token, 0, CHUNK_0).status_code == 200
    done = client.post(f"{BASE}/public/recording/finish", json={"recording_token": rec_token})
    assert done.status_code == 200
    assert _chunk(client, rec_token, 1, CHUNK_1).status_code == 404


# ------------------------------------------------------------------ playback and access


def test_admin_can_play_the_finished_recording_and_it_is_audited(  # type: ignore[no-untyped-def]
    client, video_world, store, engine
) -> None:
    headers, sid, rec_token = _recorded(client, video_world)
    # Chunks may arrive out of order (network); playback joins them in sequence.
    assert _chunk(client, rec_token, 1, CHUNK_1).status_code == 200
    assert _chunk(client, rec_token, 0, CHUNK_0).status_code == 200
    client.post(f"{BASE}/public/recording/finish", json={"recording_token": rec_token})

    listed = client.get(f"{BASE}/sessions/{sid}/recordings", headers=headers)
    assert listed.status_code == 200
    (rec,) = listed.json()
    assert rec["status"] == "complete"
    assert rec["bytes_total"] == len(CHUNK_0) + len(CHUNK_1)

    playback = client.get(f"{BASE}/recordings/{rec['id']}/playback", headers=headers)
    assert playback.status_code == 200
    assert playback.json()["url"] is None  # in-memory store: play through /stream

    stream = client.get(f"{BASE}/recordings/{rec['id']}/stream", headers=headers)
    assert stream.status_code == 200
    assert stream.content == CHUNK_0 + CHUNK_1
    assert stream.headers["content-type"].startswith("video/webm")
    assert stream.headers["cache-control"] == "no-store"
    assert "ai_interview.video_viewed" in _audit_actions(engine)
    assert "ai_interview.video_recording_started" in _audit_actions(engine)


def test_playback_waits_until_the_recording_ends(client, video_world) -> None:  # type: ignore[no-untyped-def]
    headers, sid, rec_token = _recorded(client, video_world)
    _chunk(client, rec_token, 0, CHUNK_0)
    (rec,) = client.get(f"{BASE}/sessions/{sid}/recordings", headers=headers).json()
    assert client.get(f"{BASE}/recordings/{rec['id']}/stream", headers=headers).status_code == 409


def test_people_without_pii_access_cannot_see_recordings(client, video_world) -> None:  # type: ignore[no-untyped-def]
    _, sid, rec_token = _recorded(client, video_world)
    _chunk(client, rec_token, 0, CHUNK_0)
    client.post(f"{BASE}/public/recording/finish", json={"recording_token": rec_token})
    admin = _login(client, video_world["admin_email"])
    (rec,) = client.get(f"{BASE}/sessions/{sid}/recordings", headers=admin).json()

    panel = _login(client, "panel@example.com")  # interview panel: no candidate.view_pii
    assert client.get(f"{BASE}/sessions/{sid}/recordings", headers=panel).status_code == 403
    assert client.get(f"{BASE}/recordings/{rec['id']}/stream", headers=panel).status_code == 403


def test_an_admin_of_another_campaign_cannot_open_the_recording(  # type: ignore[no-untyped-def]
    client, video_world, engine
) -> None:
    _, sid, rec_token = _recorded(client, video_world)
    _chunk(client, rec_token, 0, CHUNK_0)
    client.post(f"{BASE}/public/recording/finish", json={"recording_token": rec_token})
    admin = _login(client, video_world["admin_email"])
    (rec,) = client.get(f"{BASE}/sessions/{sid}/recordings", headers=admin).json()

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as db:
        role = db.execute(
            select(Role).where(Role.name == RoleName.RECRUITER_ADMIN.value)
        ).scalars().first()
        assert role is not None
        make_user(db, _org(db, role.organisation_id), roles=[role], password=PASSWORD,
                  email="other.admin@example.com")
        db.commit()
    other = _login(client, "other.admin@example.com")  # same role, NOT assigned to the campaign
    assert client.get(f"{BASE}/recordings/{rec['id']}/stream", headers=other).status_code == 403
    assert client.get(f"{BASE}/sessions/{sid}/recordings", headers=other).status_code == 403


def _org(db, org_id):  # type: ignore[no-untyped-def]
    from app.modules.identity.models import Organisation

    return db.get(Organisation, org_id)


# ------------------------------------------------------------------ retention


def test_retention_purge_deletes_the_video_and_is_audited(  # type: ignore[no-untyped-def]
    client, video_world, store, engine
) -> None:
    headers, sid, rec_token = _recorded(client, video_world)
    _chunk(client, rec_token, 0, CHUNK_0)
    client.post(f"{BASE}/public/recording/finish", json={"recording_token": rec_token})
    (rec,) = client.get(f"{BASE}/sessions/{sid}/recordings", headers=headers).json()

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as db:
        # Nothing is due yet.
        assert recording.purge_expired_recordings(db, store=store) == 0
        later = dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=31)
        assert recording.purge_expired_recordings(db, store=store, now=later) == 1
        db.commit()
        row = db.get(AiInterviewRecording, uuid.UUID(rec["id"]))
        assert row is not None and row.status == RecordingStatus.DELETED.value
        assert row.assembled_key is None
    assert not store._data  # noqa: SLF001 - every video byte is gone
    assert client.get(f"{BASE}/recordings/{rec['id']}/stream", headers=headers).status_code == 404
    assert "ai_interview.video_deleted" in _audit_actions(engine)


# ------------------------------------------------------------------ device check (network)


def test_network_check_endpoints(client) -> None:  # type: ignore[no-untyped-def]
    ping = client.get(f"{BASE}/public/network-check")
    assert ping.status_code == 200 and ping.content == b"ok"
    assert ping.headers["cache-control"] == "no-store"
    sample = client.get(f"{BASE}/public/network-check", params={"size": "sample"})
    assert len(sample.content) == 256 * 1024
    up = client.post(f"{BASE}/public/network-check", content=b"\x00" * 1000)
    assert up.json() == {"received": 1000}
    # Oversized uploads are refused; nothing is stored either way.
    too_big = client.post(f"{BASE}/public/network-check", content=b"\x00" * (513 * 1024))
    assert too_big.status_code == 422
    assert client.get(f"{BASE}/public/network-check", params={"size": "huge"}).status_code == 422
