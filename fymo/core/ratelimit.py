"""Shared in-process token-bucket core.

Two limiters use this: the WSGI middleware's path-prefix limiter
(fymo.core.middleware.RateLimiter) and the remote router's per-function
limiter (fymo.remote.rate_limit). They differ only in how they derive a
bucket key and a capacity for a given request; the bucket mechanics,
locking, and idle-bucket eviction are identical and live here so the two
cannot drift apart.

Same deployment story as the middleware: single-process only. Distributed
(Redis-backed) rate limiting is intentionally not in v1.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Hashable, Tuple


class _TokenBucket:
    __slots__ = ("tokens", "last_refill", "capacity", "rate")

    def __init__(self, capacity: int, rate: float):
        self.tokens: float = float(capacity)
        self.last_refill = time.monotonic()
        self.capacity = capacity
        self.rate = rate  # tokens per second

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


#: How often (in seconds) `BucketRegistry.check_key` opportunistically sweeps
#: idle buckets. A dedicated background thread isn't worth it for this,
#: request traffic itself drives the sweep, and a 60s cadence bounds the
#: sweep's own overhead to well under the cost of the token-bucket check it
#: rides along with.
_SWEEP_INTERVAL_SECONDS = 60.0


class BucketRegistry:
    """A keyed collection of token buckets with bounded memory.

    `_buckets` is otherwise unbounded: every distinct key seen gets its own
    entry that nothing ever removes, so a long-running process fielding
    traffic from many distinct clients (the normal case for anything
    public-facing) leaks memory for as long as it runs. `check_key`
    opportunistically sweeps idle buckets to bound this.
    """

    def __init__(self):
        self._buckets: Dict[Hashable, _TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _sweep_idle_buckets(self, now: float) -> None:
        """Drop buckets that have fully refilled since their last request.

        A fully-refilled bucket carries no state a brand-new one wouldn't
        also have (both start at `capacity` tokens), so evicting it doesn't
        change any client-visible behavior, the next request for that key
        just lazily recreates an identical bucket. Buckets with partial
        state (a client currently being throttled, or one that hasn't been
        idle long enough to fully refill) are left alone, since dropping
        those WOULD reset their limit early. Must be called with `_lock`
        held.
        """
        stale = [
            key
            for key, bucket in self._buckets.items()
            if bucket.tokens + (now - bucket.last_refill) * bucket.rate >= bucket.capacity
        ]
        for key in stale:
            del self._buckets[key]

    def check_key(self, key: Hashable, capacity: int, rate: float) -> Tuple[bool, int]:
        """Take one token from the bucket for `key`; return (allowed, remaining).

        Lazily creates the bucket on first sight of a key, and replaces it
        when the configured capacity changed (a config edit shouldn't keep
        serving out of a stale-sized bucket).
        """
        with self._lock:
            now = time.monotonic()
            if now - self._last_sweep >= _SWEEP_INTERVAL_SECONDS:
                self._sweep_idle_buckets(now)
                self._last_sweep = now

            bucket = self._buckets.get(key)
            if bucket is None or bucket.capacity != capacity:
                bucket = _TokenBucket(capacity=capacity, rate=rate)
                self._buckets[key] = bucket
            allowed = bucket.take()
            remaining = max(0, int(bucket.tokens))
        return allowed, remaining


def resolve_client_ip(environ: dict, trust_proxy: bool) -> str:
    """Return the client IP for rate-limit keying.

    When `trust_proxy` is on, the first hop in X-Forwarded-For is treated as
    the client IP. Only safe behind a trusted reverse proxy that overwrites
    the header (the same trust boundary as `resolve_scheme` /
    X-Forwarded-Proto).
    """
    if trust_proxy:
        xff = environ.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    return environ.get("REMOTE_ADDR", "unknown")


def retry_after_seconds(rpm: int) -> int:
    """Seconds until one token regenerates at `rpm` tokens/minute; ceil to at
    least 1 to be useful as a Retry-After value."""
    seconds_per_token = 60.0 / rpm if rpm > 0 else 60.0
    return max(1, int(seconds_per_token + 0.999))
