"""Build stage of the backend release pipeline (CodeBuild, Amazon Linux 2023, Python 3.12).

1. Compares this commit with the last released commit (SSM parameter RELEASE_PARAM) and decides
   whether anything the Lambda runs has changed, and whether new Alembic migrations were added.
2. If so, builds the Lambda package (same content as scripts/build-lambda.ps1: pinned backend
   dependencies as manylinux wheels, backend/app, Alembic migrations, the Aurora Data API driver)
   and audits its dependencies with pip-audit.
3. Writes dist/ (the pipeline artifact: lambda.zip, release.json, release.py, deploy.yml) and
   release.env (the exported pipeline variables used by the Approve/Deploy stage conditions).

Environment: RELEASE_PARAM, PIP_AUDIT_ENFORCE ("true"/"false"), FORCE_RELEASE ("true"/"false"),
LAST_RELEASED (optional override of the SSM lookup, for local runs).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Paths whose change means the Lambda code (or its dependencies) changed.
RUNTIME_PATHS: tuple[str, ...] = (
    "backend/app/",
    "backend/alembic/",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "Orient_Internal_AI_Deployment/lambda-extra-requirements.txt",
)
MIGRATIONS_DIR = "backend/alembic/versions/"
LAMBDA_UNZIPPED_LIMIT = 262_144_000  # bytes (250 MiB)
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)  # fixed timestamp: identical sources give an identical zip


@dataclass
class ChangeSet:
    known_base: bool
    runtime_files: list[str] = field(default_factory=list)
    new_migrations: list[str] = field(default_factory=list)

    def backend_changed(self, force: bool) -> bool:
        return force or not self.known_base or bool(self.runtime_files)

    def has_migrations(self) -> bool:
        # Unknown base (first release / rewritten history): assume yes, so a backup is taken.
        return not self.known_base or bool(self.new_migrations)


def classify(known_base: bool, changed: list[str], added: list[str]) -> ChangeSet:
    """Pure decision logic (unit-tested): which changed paths matter for a backend release."""
    if not known_base:
        return ChangeSet(known_base=False)
    runtime = sorted(p for p in changed if p.startswith(RUNTIME_PATHS))
    migrations = sorted(p for p in added if p.startswith(MIGRATIONS_DIR) and p.endswith(".py"))
    return ChangeSet(known_base=True, runtime_files=runtime, new_migrations=migrations)


def summary_line(cs: ChangeSet, force: bool, vuln_count: int | None, enforce: bool) -> str:
    if not cs.known_base:
        what = "first pipeline release (no previous release recorded)"
    elif cs.runtime_files:
        what = f"{len(cs.runtime_files)} runtime file(s) changed"
    elif force:
        what = "forced release (no code change; publishes current configuration)"
    else:
        what = "no backend change (Approve and Deploy are skipped)"
    names = ", ".join(Path(p).name for p in cs.new_migrations) or "none"
    parts = [what, f"new migrations: {names}"]
    if vuln_count is not None:
        mode = "blocking" if enforce else "report only"
        parts.append(f"known-vulnerable dependency findings: {vuln_count} ({mode})")
    return "; ".join(parts)[:450]


# ---------------------------------------------------------------- side-effecting helpers
# Security note (S603): every subprocess call in this file uses a fixed argument list (git, aws,
# pip) with no shell; the only variable parts are commit ids from git itself and paths in the build
# container, never user input.
def run(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)  # noqa: S603


def last_released_commit() -> str:
    override = os.environ.get("LAST_RELEASED")
    if override:
        return override
    param = os.environ["RELEASE_PARAM"]
    res = run(
        [
            "aws",
            "ssm",
            "get-parameter",
            "--name",
            param,
            "--query",
            "Parameter.Value",
            "--output",
            "text",
        ],
        check=False,
    )
    if res.returncode != 0:
        print(f"WARNING: could not read {param}; treating as first release:\n{res.stderr}")
        return "none"
    return res.stdout.strip()


def detect_changes(src: Path, base: str, head: str) -> ChangeSet:
    known = (
        base not in ("", "none")
        and run(["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=src, check=False).returncode
        == 0
    )
    if not known:
        return classify(False, [], [])
    changed = run(["git", "diff", "--name-only", base, head], cwd=src).stdout.splitlines()
    added = run(
        ["git", "diff", "--name-only", "--diff-filter=A", base, head, "--", MIGRATIONS_DIR],
        cwd=src,
    ).stdout.splitlines()
    return classify(True, changed, added)


def build_package(src: Path, pkg: Path) -> None:
    backend = src / "backend"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    deps = tomllib.loads((backend / "pyproject.toml").read_text())["project"]["dependencies"]
    req = pkg.parent / "lambda-requirements.txt"
    req.write_text("\n".join(deps) + "\n")
    pip = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-cache-dir",
        "--target",
        str(pkg),
    ]
    subprocess.run(  # noqa: S603 (fixed pip command, see note above run())
        [
            *pip,
            "-r",
            str(req),
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
        ],
        check=True,
    )
    extra = src / "Orient_Internal_AI_Deployment" / "lambda-extra-requirements.txt"
    subprocess.run([*pip, "--no-deps", "-r", str(extra), "--only-binary=:all:"], check=True)  # noqa: S603

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(backend / "app", pkg / "app", ignore=ignore)
    # "migrations", not "alembic": a folder named alembic would shadow the Alembic library.
    shutil.copytree(backend / "alembic", pkg / "migrations", ignore=ignore)
    shutil.copy2(backend / "alembic.ini", pkg / "alembic.ini")
    for cache in pkg.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def write_zip(pkg: Path, out: Path) -> int:
    """Deterministic zip (sorted entries, fixed timestamps). Returns the unzipped size."""
    total = 0
    files = sorted(p for p in pkg.rglob("*") if p.is_file())
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            rel = path.relative_to(pkg).as_posix()
            info = zipfile.ZipInfo(rel, date_time=ZIP_EPOCH)
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            data = path.read_bytes()
            total += len(data)
            zf.writestr(info, data)
    return total


def audit(pkg: Path) -> tuple[int, list[dict[str, object]]]:
    res = run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--path",
            str(pkg),
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ],
        check=False,
    )
    try:
        report = json.loads(res.stdout)
    except json.JSONDecodeError:
        print(res.stdout[-2000:], res.stderr[-2000:])
        raise RuntimeError("pip-audit did not produce a JSON report") from None
    findings: list[dict[str, object]] = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            findings.append(
                {
                    "package": dep.get("name"),
                    "version": dep.get("version"),
                    "id": vuln.get("id"),
                    "fix_versions": vuln.get("fix_versions", []),
                }
            )
    return len(findings), findings


def main() -> int:
    src = Path(os.environ.get("CODEBUILD_SRC_DIR", Path(__file__).resolve().parents[2])).resolve()
    dist = src / "dist"
    work = Path(tempfile.gettempdir()) / "ora-release-build"
    force = os.environ.get("FORCE_RELEASE", "false").strip().lower() == "true"
    enforce = os.environ.get("PIP_AUDIT_ENFORCE", "false").strip().lower() == "true"

    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)

    head = run(["git", "rev-parse", "HEAD"], cwd=src).stdout.strip()
    base = last_released_commit()
    cs = detect_changes(src, base, head)
    changed = cs.backend_changed(force)
    print(f"commit {head}  last released {base}  backend_changed={changed}")
    for p in cs.runtime_files:
        print(f"  changed: {p}")
    for p in cs.new_migrations:
        print(f"  new migration: {p}")

    release: dict[str, object] = {
        "commit": head,
        "commit_short": head[:8],
        "last_released": base,
        "backend_changed": changed,
        "forced": force,
        "has_migrations": cs.has_migrations() if changed else False,
        "runtime_files": cs.runtime_files,
        "new_migrations": cs.new_migrations,
    }
    vuln_count: int | None = None

    if changed:
        pkg = work / "pkg"
        build_package(src, pkg)
        zip_path = dist / "lambda.zip"
        unzipped = write_zip(pkg, zip_path)
        if unzipped > LAMBDA_UNZIPPED_LIMIT:
            raise RuntimeError(
                f"package is {unzipped} bytes unzipped; Lambda allows {LAMBDA_UNZIPPED_LIMIT}"
            )
        digest = hashlib.sha256(zip_path.read_bytes()).digest()
        vuln_count, findings = audit(pkg)
        release.update(
            {
                "zip_bytes": zip_path.stat().st_size,
                "unzipped_bytes": unzipped,
                "zip_sha256_hex": digest.hex(),
                # Lambda reports CodeSha256 as base64; Deploy verifies the uploaded code against it.
                "zip_sha256_b64": base64.b64encode(digest).decode(),
                "dependency_findings": findings,
            }
        )
        zipped_mb = zip_path.stat().st_size / 1e6
        print(f"package: {zipped_mb:.1f} MB zipped, {unzipped / 1e6:.1f} MB unzipped")
        print(f"pip-audit: {vuln_count} finding(s) ({'blocking' if enforce else 'report only'})")
        for f in findings:
            fixes = ", ".join(str(v) for v in f["fix_versions"]) or "n/a"  # type: ignore[attr-defined]
            print(f"  {f['package']} {f['version']}: {f['id']} (fixed in {fixes})")
        if enforce and vuln_count:
            print("FAILED: known-vulnerable dependencies (PIP_AUDIT_ENFORCE=true)")
            return 1

    summary = summary_line(cs, force, vuln_count, enforce)
    release["summary"] = summary
    (dist / "release.json").write_text(json.dumps(release, indent=2))
    # The Deploy stage runs from this artifact, so it carries its own buildspec and script.
    pipeline_dir = src / "Orient_Internal_AI_Deployment"
    shutil.copy2(pipeline_dir / "pipeline" / "release.py", dist / "release.py")
    shutil.copy2(pipeline_dir / "buildspec" / "deploy.yml", dist / "deploy.yml")

    exported = {
        "BACKEND_CHANGED": "true" if changed else "false",
        "HAS_MIGRATIONS": "true" if release["has_migrations"] else "false",
        "COMMIT": head,
        "COMMIT_SHORT": head[:8],
        "SUMMARY": summary,
    }
    (src / "release.env").write_text(
        "".join(f"{k}={shlex.quote(v)}\n" for k, v in exported.items())
    )
    print(f"summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
