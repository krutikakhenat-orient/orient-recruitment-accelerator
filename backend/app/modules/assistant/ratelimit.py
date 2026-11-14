"""Sliding-window rate limit for /assistant/ask (Req 5.4), per user and per client address.

Process-local: each server process (or Lambda container) keeps its own counters, so the
effective limit across a fleet is higher than the configured value. A shared store (for
example Redis or an API Gateway usage plan) is the follow-up for a strict global limit.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from app.core.errors import RateLimitedError


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0, max_keys: int = 10_000) -> None:
        self._window = window_seconds
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > self._max_keys:
                self._hits.clear()  # bound memory; worst case a brief reset of counters
            hits = self._hits.setdefault(key, deque())
            while hits and current - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= limit:
                raise RateLimitedError(
                    "You have asked a lot of questions in a short time. Please wait a minute."
                )
            hits.append(current)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


ask_limiter = SlidingWindowLimiter()
