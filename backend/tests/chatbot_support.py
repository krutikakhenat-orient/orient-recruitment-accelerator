"""Shared helpers for HR policy chatbot tests. Every person, policy and file is SYNTHETIC."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.modules.assistant.composer import ComposedAnswer
from app.modules.identity.permissions import RoleName
from app.modules.knowledge_base.keyword import tokens
from app.modules.knowledge_base.types import (
    AudienceFilter,
    KnowledgeBaseBusyError,
    KnowledgeBaseError,
    Passage,
    PolicyMetadata,
    SyncHandle,
    SyncState,
    SyncStatus,
    approved_key,
)
from tests.factories import make_org, make_role, make_user

PASSWORD = "CorrectHorseBatteryStaple1"


def seed_people(engine) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        org = make_org(session)
        roles = {r: make_role(session, org, r) for r in RoleName}
        people = {
            "admin": RoleName.RECRUITER_ADMIN,
            "admin2": RoleName.RECRUITER_ADMIN,
            "recruiter": RoleName.RECRUITER,
            "employee": RoleName.EMPLOYEE,
        }
        ids: dict[str, Any] = {"org_id": org.id}
        for key, role in people.items():
            user = make_user(session, org, roles=[roles[role]], password=PASSWORD,
                             email=f"{key}@example.com")
            ids[f"{key}_id"] = user.id
        session.commit()
        return ids
    finally:
        session.close()


def login(client, email: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    tokens_ = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {tokens_['access_token']}"}


# ---------------------------------------------------------------- file builders


def make_docx(text: str, *, extra: dict[str, bytes] | None = None) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.split("\n"))
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{namespace}">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def make_zip_bomb_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/padding.xml", b"0" * (20 * 1024 * 1024))  # compresses ~1000:1
    return buf.getvalue()


def make_pdf(text: str | None) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text, fontsize=11)
    data: bytes = doc.tobytes()
    doc.close()
    return data


# ---------------------------------------------------------------- fakes


class FakeBedrockKB:
    """Stands in for Bedrock: stores approved objects, runs ingestion jobs that only finish
    when the test says so, and retrieves from INDEXED objects (filtered like the real KB)."""

    name = "bedrock_kb"

    def __init__(self) -> None:
        self.objects: dict[str, PolicyMetadata] = {}
        self.texts: dict[str, str] = {}
        self.indexed: dict[str, PolicyMetadata] = {}
        self.jobs: dict[str, str] = {}
        self.fail_retrieve = False
        self.fail_put = False
        self.score = 0.9

    # data source
    def put_document(self, metadata: PolicyMetadata, data: bytes, *, extension: str,
                     content_type: str) -> str:
        if self.fail_put:
            raise KnowledgeBaseError("could not store approved file (synthetic)")
        key = approved_key(metadata, extension)
        self.objects[key] = metadata
        self.texts[key] = data.decode("utf-8", errors="ignore")
        return key

    def delete_document(self, key: str) -> None:
        self.objects.pop(key, None)
        self.texts.pop(key, None)

    def list_documents(self) -> set[str] | None:
        return set(self.objects)

    # sync
    def start_sync(self) -> SyncHandle:
        if any(state == "running" for state in self.jobs.values()):
            raise KnowledgeBaseBusyError("busy")
        job_id = f"JOB{len(self.jobs) + 1}"
        self.jobs[job_id] = "running"
        return SyncHandle(job_id=job_id)

    def get_sync_status(self, handle: SyncHandle) -> SyncStatus:
        state = self.jobs.get(handle.job_id or "", "complete")
        if state == "running":
            return SyncStatus(state=SyncState.RUNNING)
        if state == "failed":
            return SyncStatus(state=SyncState.FAILED, error="synthetic failure")
        return SyncStatus(state=SyncState.COMPLETE)

    def finish(self, job_id: str, ok: bool = True) -> None:
        self.jobs[job_id] = "complete" if ok else "failed"
        if ok:
            self.indexed = dict(self.objects)

    def running_job(self) -> str | None:
        return next((j for j, s in self.jobs.items() if s == "running"), None)

    # retrieval
    def retrieve(self, query: str, audience: AudienceFilter, top_k: int) -> list[Passage]:
        if self.fail_retrieve:
            raise KnowledgeBaseError("retrieve failed (synthetic)")
        q = tokens(query)
        out: list[Passage] = []
        for key, meta in self.indexed.items():
            if meta.organisation_id != audience.organisation_id:
                continue
            if not set(meta.audience) & audience.tags:
                continue
            text = self.texts.get(key, "")
            if q & (tokens(meta.title) | tokens(text)):
                out.append(Passage(policy_id=meta.policy_id, version=meta.version,
                                   title=meta.title, text=text[:500], score=self.score, page=1))
        return out[:top_k]


class CitingComposer:
    """Fake generation step: answers with the first passage and cites it."""

    name = "fake_converse"

    def __init__(self, text: str | None = None, citations: list[int] | None = None) -> None:
        self.text = text
        self.citations = citations
        self.calls = 0

    def compose(self, question: str, passages: list[Passage]) -> ComposedAnswer:
        self.calls += 1
        text = self.text if self.text is not None else f"{passages[0].text[:200]} [1]"
        citations = [1] if self.citations is None else self.citations
        return ComposedAnswer(text=text, citations=citations)
