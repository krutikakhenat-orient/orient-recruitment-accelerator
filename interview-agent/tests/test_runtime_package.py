"""The AgentCore package installs from src/pyproject.toml; it must not drift from the dev project."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _deps(path: Path) -> list[str]:
    return sorted(tomllib.loads(path.read_text("utf-8"))["project"]["dependencies"])


def test_runtime_dependencies_match_project() -> None:
    assert _deps(ROOT / "src" / "pyproject.toml") == _deps(ROOT / "pyproject.toml")


def test_runtime_entrypoint_exists() -> None:
    assert (ROOT / "src" / "main.py").is_file()
