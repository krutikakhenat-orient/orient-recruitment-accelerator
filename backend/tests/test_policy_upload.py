"""HR policy upload: validation, quarantine, scan, duplicates, typed-in Markdown (Req 1, 3.6).

All files are SYNTHETIC and built in the test.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.modules.documents.scanning import EICAR
from app.modules.documents.storage import InMemoryObjectStore
from app.modules.knowledge_base.deps import get_policy_file_store
from app.modules.policies.models import PolicyDocument
from tests.chatbot_support import login, make_docx, make_pdf, make_zip_bomb_docx, seed_people
from tests.factories import make_org

LEAVE_TEXT = (
    "SYNTHETIC leave policy. Employees receive 20 days of paid annual leave each year. "
    "Unused leave can be carried forward up to 5 days."
)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def hr(client, engine, store):  # type: ignore[no-untyped-def]
    ids = seed_people(engine)
    client.app.dependency_overrides[get_policy_file_store] = lambda: store
    return {**ids, "admin": login(client, "admin@example.com"),
            "recruiter": login(client, "recruiter@example.com"),
            "employee": login(client, "employee@example.com")}


def _upload(client, headers, name, data, ctype, **form):  # type: ignore[no-untyped-def]
    # Most tests here check the file handling on a draft ("Save as draft"); the publish-on-
    # upload default has its own tests below.
    fields = {"title": "SYNTHETIC Leave policy", "publish": "false",
              **{k: str(v) for k, v in form.items()}}
    return client.post("/api/v1/policies/upload", headers=headers, data=fields,
                       files={"file": (name, data, ctype)})


def _keys(store: InMemoryObjectStore) -> list[str]:
    return sorted(store._data)  # noqa: SLF001 - test inspection of the in-memory store


@pytest.mark.parametrize("name,builder,ctype", [
    ("leave.txt", lambda: LEAVE_TEXT.encode(), "text/plain"),
    ("leave.md", lambda: f"# Leave\n\n{LEAVE_TEXT}".encode(), "text/markdown"),
    ("leave.docx", lambda: make_docx(LEAVE_TEXT), DOCX),
    ("leave.pdf", lambda: make_pdf(LEAVE_TEXT), "application/pdf"),
], ids=["txt", "md", "docx", "pdf"])
def test_supported_files_become_drafts_in_draft_prefix(client, hr, store, name, builder,  # type: ignore[no-untyped-def]
                                                       ctype) -> None:
    resp = _upload(client, hr["admin"], name, builder(), ctype,
                   audience="role:recruiter", review_due_date="2027-01-31")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft" and body["has_file"] is True
    assert body["audience"] == ["role:recruiter"] and body["review_due_date"] == "2027-01-31"
    assert "20 days" in body["body"]
    assert body["source_filename"] == name and body["index_status"] == "not_indexed"
    keys = _keys(store)
    assert len(keys) == 1 and keys[0].startswith("draft/")  # quarantine copy removed


def test_upload_requires_policy_permission(client, hr) -> None:  # type: ignore[no-untyped-def]
    for who in ("recruiter", "employee"):
        resp = _upload(client, hr[who], "a.txt", LEAVE_TEXT.encode(), "text/plain")
        assert resp.status_code == 403


@pytest.mark.parametrize("name,data,ctype,fragment", [
    ("leave.exe", b"MZ synthetic", "application/octet-stream", "Only PDF, DOCX, TXT and MD"),
    ("leave.pdf", LEAVE_TEXT.encode(), "application/pdf", "does not match"),  # fake extension
    ("leave.txt", LEAVE_TEXT.encode(), "application/pdf", "type does not match"),  # bad MIME
    ("leave.docx", make_zip_bomb_docx(), DOCX, "unsafe size"),
    ("leave.docx", make_docx(LEAVE_TEXT, extra={"word/vbaProject.bin": b"synthetic"}), DOCX,
     "macros"),
    ("leave.pdf", make_pdf(None), "application/pdf", "could not read any text"),  # scanned
    ("leave.txt", b"", "text/plain", "empty"),
], ids=["exe", "fake-extension", "bad-mime", "zip-bomb", "macro", "scanned-pdf", "empty"])
def test_unsafe_or_unreadable_files_are_rejected_and_not_stored(client, hr, store, name, data,  # type: ignore[no-untyped-def]
                                                                ctype, fragment) -> None:
    resp = _upload(client, hr["admin"], name, data, ctype)
    assert resp.status_code == 422, resp.text
    assert fragment.lower() in resp.json()["error"]["message"].lower()
    assert _keys(store) == []


def test_pdf_with_javascript_is_rejected(client, hr, store) -> None:  # type: ignore[no-untyped-def]
    data = make_pdf(LEAVE_TEXT).replace(b"%%EOF", b"<< /S /JavaScript /JS (app.alert(1)) >>\n%%EOF")
    resp = _upload(client, hr["admin"], "leave.pdf", data, "application/pdf")
    assert resp.status_code == 422 and "scripts" in resp.json()["error"]["message"]
    assert _keys(store) == []


def test_malware_is_rejected_after_quarantine(client, hr, store) -> None:  # type: ignore[no-untyped-def]
    resp = _upload(client, hr["admin"], "leave.txt", LEAVE_TEXT.encode() + b"\n" + EICAR,
                   "text/plain")
    assert resp.status_code == 422 and "security scan" in resp.json()["error"]["message"]
    assert _keys(store) == []


def test_oversize_file_is_rejected(client, hr, store, test_settings) -> None:  # type: ignore[no-untyped-def]
    test_settings.upload_max_bytes = 2048
    resp = _upload(client, hr["admin"], "leave.txt", b"a" * 4096, "text/plain")
    assert resp.status_code == 422 and "limit" in resp.json()["error"]["message"]


def test_path_traversal_filename_never_reaches_storage_key(client, hr, store) -> None:  # type: ignore[no-untyped-def]
    resp = _upload(client, hr["admin"], "../../etc/passwd.txt", LEAVE_TEXT.encode(), "text/plain")
    assert resp.status_code == 201
    assert resp.json()["source_filename"] == "passwd.txt"
    assert all(".." not in k and "passwd" not in k for k in _keys(store))


def test_duplicate_upload_warns_then_allows_with_confirmation(client, hr) -> None:  # type: ignore[no-untyped-def]
    first = _upload(client, hr["admin"], "leave.txt", LEAVE_TEXT.encode(), "text/plain")
    assert first.status_code == 201
    again = _upload(client, hr["admin"], "copy.txt", LEAVE_TEXT.encode(), "text/plain")
    assert again.status_code == 409
    dupes = again.json()["error"]["details"]["duplicates"]
    assert dupes[0]["id"] == first.json()["id"]
    confirmed = _upload(client, hr["admin"], "copy.txt", LEAVE_TEXT.encode(), "text/plain",
                        confirm_duplicate="true")
    assert confirmed.status_code == 201


def test_bad_audience_tag_is_rejected(client, hr) -> None:  # type: ignore[no-untyped-def]
    resp = _upload(client, hr["admin"], "leave.txt", LEAVE_TEXT.encode(), "text/plain",
                   audience="role:recruiter,<script>")
    assert resp.status_code == 422


def test_upload_publishes_and_syncs_by_default(client, hr) -> None:  # type: ignore[no-untyped-def]
    # One step: the file is live, synced (keyword backend syncs at once) and answerable.
    resp = _upload(client, hr["admin"], "leave.txt", LEAVE_TEXT.encode(), "text/plain",
                   publish="true")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "approved" and body["index_status"] == "ready"
    answer = client.post("/api/v1/assistant/ask", headers=hr["employee"],
                         json={"question": "How many days of paid annual leave?"}).json()
    assert answer["answered"] is True
    assert answer["sources"][0]["title"] == "SYNTHETIC Leave policy"


def test_typed_policy_publishes_by_default_and_draft_is_opt_in(client, hr) -> None:  # type: ignore[no-untyped-def]
    live = client.post("/api/v1/policies", headers=hr["admin"],
                       json={"title": "SYNTHETIC Dress code",
                             "body": "Business casual on weekdays."})
    assert live.status_code == 201 and live.json()["status"] == "approved"
    assert live.json()["index_status"] == "ready"
    draft = client.post("/api/v1/policies", headers=hr["admin"],
                        json={"title": "SYNTHETIC Travel", "body": "Book travel via HR.",
                              "publish": False})
    assert draft.json()["status"] == "draft" and draft.json()["index_status"] == "not_indexed"
    titles = [p["title"] for p in client.get("/api/v1/policies", headers=hr["employee"]).json()]
    assert "SYNTHETIC Dress code" in titles and "SYNTHETIC Travel" not in titles


def test_typed_in_policy_is_stored_as_markdown(client, hr, store) -> None:  # type: ignore[no-untyped-def]
    resp = client.post("/api/v1/policies", headers=hr["admin"], json={
        "title": "SYNTHETIC FAQ", "kind": "faq", "body": "Q: Dress code? A: Business casual."})
    assert resp.status_code == 201 and resp.json()["has_file"] is True
    key = _keys(store)[0]
    assert key.startswith("draft/") and key.endswith(".md")
    assert store.get(key).startswith(b"# SYNTHETIC FAQ")


def test_uploaded_text_cannot_be_edited_but_file_can_be_replaced(client, hr, store) -> None:  # type: ignore[no-untyped-def]
    pid = _upload(client, hr["admin"], "leave.txt", LEAVE_TEXT.encode(), "text/plain").json()["id"]
    edit = client.put(f"/api/v1/policies/{pid}", headers=hr["admin"], json={"body": "changed"})
    assert edit.status_code == 409
    new_text = LEAVE_TEXT.replace("20 days", "22 days")
    replaced = client.post(f"/api/v1/policies/{pid}/file", headers=hr["admin"],
                           files={"file": ("leave-v2.txt", new_text.encode(), "text/plain")})
    assert replaced.status_code == 200 and "22 days" in replaced.json()["body"]
    assert len(_keys(store)) == 1


def test_open_original_is_hr_only_and_an_attachment(client, hr) -> None:  # type: ignore[no-untyped-def]
    pid = _upload(client, hr["admin"], "leave.txt", LEAVE_TEXT.encode(), "text/plain").json()["id"]
    resp = client.get(f"/api/v1/policies/{pid}/original", headers=hr["admin"])
    assert resp.status_code == 200 and resp.content == LEAVE_TEXT.encode()
    assert resp.headers["content-disposition"].startswith("attachment")
    assert resp.headers["x-content-type-options"] == "nosniff"
    link = client.get(f"/api/v1/policies/{pid}/original-link", headers=hr["admin"]).json()
    assert link == {"url": None, "expires_in": None}  # in-memory store: no signed links
    assert client.get(f"/api/v1/policies/{pid}/original",
                      headers=hr["employee"]).status_code == 403


def test_other_organisation_policy_is_unreachable(client, hr, engine) -> None:  # type: ignore[no-untyped-def]
    # Sign-in resolves the single active organisation (MVP), so the foreign policy is
    # created directly and requested by this organisation's HR admin.
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    other = make_org(session, name="SYNTHETIC Other Org")
    foreign = PolicyDocument(organisation_id=other.id, family_id=uuid.uuid4(),
                             title="SYNTHETIC foreign", kind="policy", body="foreign text",
                             version=1, status="draft", source_key="draft/x/y/v1/policy.md")
    session.add(foreign)
    session.commit()
    pid = foreign.id
    session.close()
    for path in (f"/api/v1/policies/{pid}/original", f"/api/v1/policies/{pid}/index-status"):
        assert client.get(path, headers=hr["admin"]).status_code == 404
    assert client.post(f"/api/v1/policies/{pid}/approve", headers=hr["admin"]).status_code == 404
