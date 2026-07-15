"""WSGI middleware for production hardening: rate limit, body cap, security headers.

Designed for single-process deployments. Distributed rate limiting (Redis-backed)
is intentionally not in v1; document and revisit when someone runs >1 worker
behind a load balancer and needs cross-worker bucket sharing.

Each piece is configured via `fymo.yml`:

    limits:
      rate_limit:
        enabled: true
        requests_per_minute: 60
        paths:
          "/_fymo/remote/": 30
        trust_proxy: false
      max_body_bytes: 10485760  # 10 MB

    security:
      headers:
        enabled: true
        extra:
          - ["Content-Security-Policy", "default-src 'self'"]

In production (`dev=False`) two defaults apply on top of the always-on
headers below, unless overridden via `security.headers.extra` above:

- `Content-Security-Policy-Report-Only` (a sensible `default-src 'self'`
  baseline) — report-only so it can never break an app out of the box.
  See `DEFAULT_CSP_REPORT_ONLY` and docs/deployment.md for tightening it
  to an enforcing policy with nonces.
- `Strict-Transport-Security`, added when the *resolved* request scheme
  (`resolve_scheme`, honoring `X-Forwarded-Proto` only when
  `rate_limit.trust_proxy` is on) is https — so it still fires behind a
  TLS-terminating reverse proxy.

Both are skipped in dev (`dev=True`).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from fymo.core.config import parse_bool


# ---------------- Rate limiter ----------------


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool = True
    default_rpm: int = 60
    # Path-prefix → rpm. Longest matching prefix wins; falls back to default_rpm.
    path_rules: Dict[str, int] = field(default_factory=dict)
    # When True, the first hop in X-Forwarded-For is treated as the client IP.
    # Only safe behind a trusted reverse proxy that overwrites the header.
    trust_proxy: bool = False


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


#: How often (in seconds) `RateLimiter.check` opportunistically sweeps idle
#: buckets. A dedicated background thread isn't worth it for this -- request
#: traffic itself drives the sweep, and a 60s cadence bounds the sweep's own
#: overhead to well under the cost of the token-bucket check it rides along
#: with.
_SWEEP_INTERVAL_SECONDS = 60.0


class RateLimiter:
    """Per-(IP, rule) token bucket rate limiter, in-process.

    `_buckets` is otherwise unbounded: every distinct (client_ip, rule)
    pair seen gets its own entry that nothing ever removes, so a
    long-running process fielding traffic from many distinct IPs (the
    normal case for anything public-facing) leaks memory for as long as it
    runs. `check` opportunistically sweeps idle buckets to bound this.
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._buckets: Dict[Tuple[str, str], _TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _sweep_idle_buckets(self, now: float) -> None:
        """Drop buckets that have fully refilled since their last request.

        A fully-refilled bucket carries no state a brand-new one wouldn't
        also have (both start at `capacity` tokens), so evicting it doesn't
        change any client-visible behavior -- the next request for that key
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

    def client_ip(self, environ: dict) -> str:
        if self.config.trust_proxy:
            xff = environ.get("HTTP_X_FORWARDED_FOR", "")
            if xff:
                first = xff.split(",", 1)[0].strip()
                if first:
                    return first
        return environ.get("REMOTE_ADDR", "unknown")

    def _rule_for_path(self, path: str) -> Tuple[int, str]:
        """Return (rpm, rule_key). Longest matching prefix wins."""
        best: Optional[Tuple[str, int]] = None
        for prefix, rpm in self.config.path_rules.items():
            if path.startswith(prefix):
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, rpm)
        if best is not None:
            return best[1], best[0]
        return self.config.default_rpm, ""

    def check(self, environ: dict) -> Tuple[bool, Dict[str, int]]:
        """Return (allowed, info). `info` carries limit, remaining, retry_after.

        retry_after is 0 when the request is allowed; otherwise it's the seconds
        until the next token is available (always ≥ 1 to be useful as Retry-After).
        """
        if not self.config.enabled:
            return True, {"limit": 0, "remaining": 0, "retry_after": 0}

        path = environ.get("PATH_INFO", "/")
        ip = self.client_ip(environ)
        rpm, rule_key = self._rule_for_path(path)
        scope_key = (ip, rule_key)

        with self._lock:
            now = time.monotonic()
            if now - self._last_sweep >= _SWEEP_INTERVAL_SECONDS:
                self._sweep_idle_buckets(now)
                self._last_sweep = now

            bucket = self._buckets.get(scope_key)
            if bucket is None or bucket.capacity != rpm:
                bucket = _TokenBucket(capacity=rpm, rate=rpm / 60.0)
                self._buckets[scope_key] = bucket
            allowed = bucket.take()
            remaining = max(0, int(bucket.tokens))

        info = {"limit": rpm, "remaining": remaining, "retry_after": 0}
        if not allowed:
            # Seconds until 1 token regenerates; ceil to at least 1.
            seconds_per_token = 60.0 / rpm if rpm > 0 else 60.0
            info["retry_after"] = max(1, int(seconds_per_token + 0.999))
        return allowed, info


# ---------------- Scheme resolution (Secure cookie flag behind a proxy) ----------------


def resolve_scheme(environ: dict, trust_proxy: bool) -> str:
    """Return the true request scheme, honoring X-Forwarded-Proto when trusted.

    A TLS-terminating reverse proxy speaks plain http to the app, so
    `wsgi.url_scheme` reads "http" even though the client connected over
    https — which would otherwise ship cookies (e.g. the session cookie)
    without `Secure`. Only trust the forwarded header behind a proxy that
    overwrites it (same trust boundary as `RateLimitConfig.trust_proxy` /
    `X-Forwarded-For`); otherwise a client could spoof
    `X-Forwarded-Proto: https` over plain http to force `Secure` on with no
    actual TLS behind it.
    """
    if trust_proxy:
        forwarded = environ.get("HTTP_X_FORWARDED_PROTO", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip().lower()
    return environ.get("wsgi.url_scheme", "http")


# ---------------- Body cap ----------------


def check_body_limit(environ: dict, max_bytes: int) -> bool:
    """True if the request body is within the cap (or size unknown).

    Only inspects Content-Length. Chunked-transfer-encoded bodies have no
    Content-Length header; for those, the downstream handler that actually
    reads `wsgi.input` is responsible for limiting bytes read. fymo's remote
    router and soft-nav handler both do this implicitly by capping their reads.
    """
    cl = environ.get("CONTENT_LENGTH", "")
    if not cl:
        return True
    try:
        return int(cl) <= max_bytes
    except ValueError:
        return True


# ---------------- Security headers ----------------


DEFAULT_SECURITY_HEADERS: List[Tuple[str, str]] = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
]


# Default production CSP, shipped in *report-only* mode.
#
# Why report-only and not enforcing: fymo's own SSR page embeds a
# `<script type="module" src=...>` for hydration (same-origin, allowed by
# `script-src 'self'`) but apps commonly opt into inline `<script>` blocks
# via `fymo.yml`'s `head.script.analyticsID` / `hotjar` / `custom` config
# (see `fymo/core/template_renderer.py`), plus third-party script hosts
# (Google Tag Manager, Hotjar). A strict enforcing `script-src 'self'`
# would silently break those out of the box. Report-only ships a sensible
# baseline *and* surfaces violations (via the browser console, or a
# report-uri/report-to endpoint if configured) without breaking anything.
#
# See docs/deployment.md for how to move to an enforcing policy with
# nonces once inline scripts are audited.
DEFAULT_CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)

_CSP_HEADER_NAMES = {"content-security-policy", "content-security-policy-report-only"}


def security_headers_for(
    environ: dict,
    extra: Optional[List[Tuple[str, str]]] = None,
    *,
    dev: bool = False,
    trust_proxy: bool = False,
) -> List[Tuple[str, str]]:
    """Return the headers to inject for this request.

    Production defaults (dev=False):
    - A default `Content-Security-Policy-Report-Only` is added when no CSP
      (enforcing or report-only) is already present in `extra` — i.e. the
      app hasn't configured its own via `security.headers.extra` in
      `fymo.yml`. Report-only so it can never break an app out of the box.
    - HSTS is added when the *resolved* scheme (see `resolve_scheme`) is
      https. Behind a trusted reverse proxy (`trust_proxy=True`) this
      honors `X-Forwarded-Proto`; otherwise only a direct https connection
      counts, so a client can't spoof the header to force HSTS on.

    In dev (dev=True) neither default is applied — no CSP noise locally,
    and HSTS is never forced (it would break plain-http localhost, and
    persists in the browser's HSTS cache well past the dev session).
    """
    out = list(DEFAULT_SECURITY_HEADERS)
    if extra:
        out.extend(extra)

    if not dev:
        has_csp = any(k.lower() in _CSP_HEADER_NAMES for k, _ in out)
        if not has_csp:
            out.append(("Content-Security-Policy-Report-Only", DEFAULT_CSP_REPORT_ONLY))

        if resolve_scheme(environ, trust_proxy) == "https":
            out.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))

    return out


def wrap_start_response(
    start_response: Callable,
    environ: dict,
    extra_headers: Optional[List[Tuple[str, str]]] = None,
    *,
    dev: bool = False,
    trust_proxy: bool = False,
) -> Callable:
    """Return a wrapped start_response that injects security headers.

    Existing headers wins — we never overwrite a header the handler already
    set. This lets specific routes opt out by setting their own value.
    """
    to_add = security_headers_for(environ, extra_headers, dev=dev, trust_proxy=trust_proxy)

    def wrapped(status: str, response_headers: List[Tuple[str, str]], exc_info=None):
        existing = {k.lower() for k, _ in response_headers}
        for k, v in to_add:
            if k.lower() not in existing:
                response_headers.append((k, v))
        # Per PEP 3333, exc_info is optional. Test stubs sometimes implement
        # start_response with the 2-arg signature; only pass it through when
        # the caller actually provided it.
        if exc_info is not None:
            return start_response(status, response_headers, exc_info)
        return start_response(status, response_headers)

    return wrapped


# ---------------- Pre-handler responses (used by FymoApp.__call__) ----------------


def respond_413(start_response, max_bytes: int) -> Iterable[bytes]:
    body = f"Payload Too Large (max {max_bytes} bytes)".encode("utf-8")
    start_response("413 Payload Too Large", [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ])
    return [body]


def respond_429(start_response, info: Dict[str, int]) -> Iterable[bytes]:
    body = b"Too Many Requests"
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Retry-After", str(info["retry_after"])),
        ("X-RateLimit-Limit", str(info["limit"])),
        ("X-RateLimit-Remaining", "0"),
    ]
    start_response("429 Too Many Requests", headers)
    return [body]


# ---------------- Settings loader ----------------


# Default body cap: 10 MB. Big enough for any reasonable JSON payload or file
# upload through fymo's remote functions, small enough to short-circuit
# obvious abuse.
DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class MiddlewareSettings:
    """Resolved middleware configuration."""
    rate_limit_config: RateLimitConfig
    max_body_bytes: int
    security_headers_enabled: bool
    extra_security_headers: List[Tuple[str, str]] = field(default_factory=list)
    # Gates the default CSP-Report-Only + HSTS-over-resolved-scheme defaults
    # in `security_headers_for` — production only (dev=False). Threaded in
    # from `FymoApp.dev` at construction time.
    dev: bool = False

    @classmethod
    def from_yaml(cls, limits: dict, security: dict, dev: bool = False) -> "MiddlewareSettings":
        rl = (limits or {}).get("rate_limit", {}) or {}
        path_rules = {}
        for prefix, rpm in (rl.get("paths") or {}).items():
            try:
                path_rules[str(prefix)] = int(rpm)
            except (TypeError, ValueError):
                continue

        rate_limit_config = RateLimitConfig(
            # Defaults to enabled in production, disabled in dev -- a single
            # developer's browser tabs, soft-nav clicks, and page reloads all
            # share one token bucket (same REMOTE_ADDR) for the whole life of
            # `fymo dev`, so the production-sane default of 60/min is easy to
            # exhaust during ordinary local testing. Still fully overridable
            # either direction via an explicit `rate_limit.enabled` in
            # fymo.yml, in prod or in dev.
            enabled=parse_bool(rl.get("enabled", not dev), field="limits.rate_limit.enabled"),
            default_rpm=int(rl.get("requests_per_minute", 60)),
            path_rules=path_rules,
            trust_proxy=parse_bool(rl.get("trust_proxy", False), field="limits.rate_limit.trust_proxy"),
        )

        max_body_bytes = int((limits or {}).get("max_body_bytes", DEFAULT_MAX_BODY_BYTES))

        sec = (security or {}).get("headers", {}) or {}
        security_enabled = parse_bool(sec.get("enabled", True), field="security.headers.enabled")
        extra: List[Tuple[str, str]] = []
        for entry in sec.get("extra", []) or []:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                extra.append((str(entry[0]), str(entry[1])))

        return cls(
            rate_limit_config=rate_limit_config,
            max_body_bytes=max_body_bytes,
            security_headers_enabled=security_enabled,
            extra_security_headers=extra,
            dev=bool(dev),
        )
