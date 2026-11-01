"""Tiny in-memory sliding-window rate limiter (single process, which is how the demo runs)."""
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record an attempt for key; False when it exceeds `limit` attempts within the window. limit<=0 disables."""
        if self.limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def peek(self, key: str) -> bool:
        """True when `key` is below the limit (records nothing)."""
        if self.limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            return len(hits) < self.limit

    def hit(self, key: str) -> None:
        """Record one event for `key` (used for failed logins)."""
        if self.limit <= 0:
            return
        with self._lock:
            self._hits[key].append(self._clock())

    def retry_after(self, key: str) -> int:
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            return max(1, int(self.window_s - (self._clock() - hits[0])) + 1)
