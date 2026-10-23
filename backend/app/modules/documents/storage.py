"""Object-storage abstraction (ADR-0004).

Files are only ever accessed through this interface, never via a public URL. The MVP
ships an in-memory/local implementation suitable for tests and local dev; a MinIO/S3
implementation can be dropped in without changing callers. Downloads are always via
short-lived references the application mints, not direct bucket access.
"""

from __future__ import annotations

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


# Default instance used by the running app (replaced with MinIO/S3 in deployment config).
default_object_store: ObjectStore = InMemoryObjectStore()
