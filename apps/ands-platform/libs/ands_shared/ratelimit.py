"""Token-bucket rate limiting — pure, thread-safe (G-P2-07 / SAAS abuse guard).

Per-key buckets refill at ``rate`` tokens/sec up to ``burst``; each allowed
request spends one token. Clock-injectable for deterministic tests; the app
factory wires it as middleware keyed by tenant (or client host).
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    __slots__ = ("rate", "capacity", "tokens", "updated")

    def __init__(self, rate: float, burst: int) -> None:
        self.rate = float(rate)
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated = 0.0

    def allow(self, now: float) -> bool:
        if self.updated == 0.0:
            self.updated = now
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimiter:
    def __init__(self, rate: float, burst: int) -> None:
        self.rate = float(rate)
        self.burst = int(burst)
        self._buckets: dict = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(self.rate, self.burst)
                self._buckets[key] = bucket
            return bucket.allow(t)
