"""Unit tests for the release pipeline scripts (no AWS, no network).

Run from the repo root with the backend venv:
  backend\\.venv\\Scripts\\python -m pytest Orient_Internal_AI_Deployment/pipeline/tests -q
"""

from __future__ import annotations

import datetime as dt
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_package as bp  # noqa: E402
import release as rl  # noqa: E402


def test_frontend_and_docs_changes_do_not_release_the_backend() -> None:
    cs = bp.classify(
        True,
        ["frontend/src/App.tsx", "docs/USER_GUIDE.md", "backend/tests/test_x.py", "amplify.yml"],
        [],
    )
    assert cs.runtime_files == []
    assert cs.backend_changed(force=False) is False
    assert cs.has_migrations() is False


def test_runtime_changes_release_the_backend() -> None:
    changed = [
        "backend/app/main.py",
        "backend/pyproject.toml",
        "Orient_Internal_AI_Deployment/lambda-extra-requirements.txt",
        "frontend/src/App.tsx",
    ]
    cs = bp.classify(True, changed, [])
    assert cs.runtime_files == sorted(changed[:3])
    assert cs.backend_changed(force=False) is True


def test_new_migration_files_are_detected() -> None:
    added = ["backend/alembic/versions/0013_new.py", "backend/alembic/versions/README"]
    cs = bp.classify(True, ["backend/alembic/versions/0013_new.py"], added)
    assert cs.new_migrations == ["backend/alembic/versions/0013_new.py"]
    assert cs.has_migrations() is True


def test_unknown_base_releases_and_assumes_migrations() -> None:
    cs = bp.classify(False, [], [])
    assert cs.backend_changed(force=False) is True
    assert cs.has_migrations() is True  # take a backup when we cannot tell


def test_force_release_without_code_change() -> None:
    cs = bp.classify(True, ["docs/x.md"], [])
    assert cs.backend_changed(force=True) is True
    assert "forced release" in bp.summary_line(cs, force=True, vuln_count=None, enforce=False)


def test_summary_mentions_migrations_and_audit_mode() -> None:
    cs = bp.classify(True, ["backend/app/a.py"], ["backend/alembic/versions/0013_x.py"])
    line = bp.summary_line(cs, force=False, vuln_count=3, enforce=False)
    assert "1 runtime file(s) changed" in line
    assert "0013_x.py" in line
    assert "3 (report only)" in line
    assert len(line) <= 450


def test_zip_is_deterministic(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    (pkg / "app").mkdir(parents=True)
    (pkg / "app" / "b.py").write_bytes(b"b = 2\n")
    (pkg / "app" / "a.py").write_bytes(b"a = 1\n")
    first, second = tmp_path / "1.zip", tmp_path / "2.zip"
    size = bp.write_zip(pkg, first)
    bp.write_zip(pkg, second)
    assert first.read_bytes() == second.read_bytes()
    assert size == 12
    with zipfile.ZipFile(first) as zf:
        assert zf.namelist() == ["app/a.py", "app/b.py"]


def test_health_event_targets_health_route() -> None:
    event = rl.health_event()
    assert event["version"] == "2.0"
    assert event["rawPath"] == "/health"
    assert event["requestContext"]["http"]["method"] == "GET"


def test_snapshot_id_is_a_valid_rds_identifier() -> None:
    sid = rl.snapshot_id("fd4c3e5a", dt.datetime(2026, 11, 9, 14, 5, tzinfo=dt.UTC))
    assert sid == "ora-pre-fd4c3e5a-202611091405"
    assert sid[0].isalpha() and "--" not in sid and len(sid) <= 255


# ---------------------------------------------------------------- UAT -> production promotion
def test_release_targets_parse_in_order(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "RELEASE_TARGETS", "uat=/ora-uat/release/last-commit;prod=/ora-staging/release/last-commit"
    )
    assert bp.release_targets() == [
        ("uat", "/ora-uat/release/last-commit"),
        ("prod", "/ora-staging/release/last-commit"),
    ]


def test_release_targets_fall_back_to_single_prod(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RELEASE_TARGETS", raising=False)
    monkeypatch.setenv("RELEASE_PARAM", "/ora-staging/release/last-commit")
    assert bp.release_targets() == [("prod", "/ora-staging/release/last-commit")]


def test_per_target_override_of_last_released(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("LAST_RELEASED", raising=False)
    monkeypatch.setenv("LAST_RELEASED_UAT", "abc123")
    assert bp.last_released_commit("uat", "/x") == "abc123"
    assert bp.last_released_commit("prod", "") == "none"


def test_target_view_uses_that_environments_decision() -> None:
    release = {
        "commit": "c1",
        "backend_changed": True,
        "has_migrations": True,
        "zip_sha256_b64": "hash",
        "targets": {
            "uat": {"backend_changed": False, "has_migrations": False},
            "prod": {"backend_changed": True, "has_migrations": True},
        },
    }
    uat = rl.target_view(release, "uat")
    assert uat["backend_changed"] is False and uat["has_migrations"] is False
    assert uat["zip_sha256_b64"] == "hash"  # same package for every environment
    prod = rl.target_view(release, "prod")
    assert prod["backend_changed"] is True and prod["has_migrations"] is True


def test_target_view_without_targets_is_unchanged() -> None:
    release = {"backend_changed": True}
    assert rl.target_view(release, "prod") == release
    assert rl.target_view(release, "") == release
