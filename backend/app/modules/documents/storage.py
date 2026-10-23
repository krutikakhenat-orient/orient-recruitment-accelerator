"""Object-storage abstraction (ADR-0004).

Files are only ever accessed through this interface, never via a public URL. The MVP
ships an in-memory/local implementation suitable for tests and local dev; a MinIO/S3
implementation can be dropped in without changing callers. Downloads are always via
short-lived references the application mints, not direct bucket access.
"""

from __future__ import annotations

import hashlib
import pathlib
import threading
from typing import Protocol


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class InMemoryObjectStore:
    """Thread-safe in-memory store for tests and local development only."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            self._data[key] = data

    def get(self, key: str) -> bytes:
        with self._lock:
            if key not in self._data:
                raise KeyError(key)
            return self._data[key]

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._data


class LocalDiskObjectStore:
    """Disk-backed object store for LOCAL DEVELOPMENT only.

    Unlike the in-memory store, files persist across process restarts, so an uploaded resume
    is still downloadable after the dev server is restarted (the in-memory store loses every
    blob on restart, which made the Interview Panel's Resume tab show 'No resume available'
    for candidates who applied before the last restart). Keys may contain a '/' (e.g.
    'docx/<uuid>.docx'); they are mapped to a safe flat filename on disk so no directory
    traversal is possible. Production uses MinIO/S3 behind this same interface.
    """

    def __init__(self, root: str) -> None:
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, key: str) -> pathlib.Path:
        # Flatten the key to a safe filename; a hash suffix keeps it unique and prevents any
        # path-traversal from a crafted key.
        safe = key.replace("/", "_").replace("\\", "_")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self._root / f"{safe}.{digest}"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            self._path(key).write_bytes(data)

    def get(self, key: str) -> bytes:
        with self._lock:
            path = self._path(key)
            if not path.exists():
                raise KeyError(key)
            return path.read_bytes()

    def delete(self, key: str) -> None:
        with self._lock:
            self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        with self._lock:
            return self._path(key).exists()


def _build_default_store() -> ObjectStore:
    """Choose the object store at import time.

    If ``ORA_LOCAL_OBJECT_STORE_DIR`` is set (run_local.py sets it for local dev), use a
    disk-backed store so uploaded resumes PERSIST across dev server restarts. Otherwise use
    the in-memory store (tests, and the default when no deployment store is configured).
    Production overrides this with a MinIO/S3 implementation behind the same interface."""
    import os

    root = os.environ.get("ORA_LOCAL_OBJECT_STORE_DIR")
    if root:
        return LocalDiskObjectStore(root)
    return InMemoryObjectStore()


# Default instance used by the running app (replaced with MinIO/S3 in deployment config).
default_object_store: ObjectStore = _build_default_store()
