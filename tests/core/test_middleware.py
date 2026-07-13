"""Rate limiter, body cap, security headers — unit tests."""
import time
import pytest

from fymo.core.middleware import (
    DEFAULT_MAX_BODY_BYTES,
    MiddlewareSettings,
    RateLimitConfig,
    RateLimiter,
    check_body_limit,
    security_headers_for,
    wrap_start_response,
    _TokenBucket,
)


# ---------------- Token bucket ----------------


def test_bucket_starts_at_capacity():
    b = _TokenBucket(capacity=5, rate=1.0)
    assert all(b.take() for _ in range(5))
    assert b.take() is False


def test_bucket_refills_over_time():
    b = _TokenBucket(capacity=10, rate=10.0)  # 10 tokens/sec
    for _ in range(10):
        b.take()
    assert b.take() is False
    time.sleep(0.25)  # should regenerate ~2.5 tokens
    assert b.take() is True
    assert b.take() is True
    # Not enough time for a 3rd
    assert b.take() is False


# ---------------- Rate limiter ----------------


def _env(path: str = "/", ip: str = "1.2.3.4", xff: str | None = None) -> dict:
    e = {"PATH_INFO": path, "REMOTE_ADDR": ip}
    if xff is not None:
        e["HTTP_X_FORWARDED_FOR"] = xff
    return e


def test_rate_limit_disabled_passes_everything():
    rl = RateLimiter(RateLimitConfig(enabled=False, default_rpm=1))
    for _ in range(100):
        allowed, _ = rl.check(_env())
        assert allowed is True


def test_default_rpm_limit_blocks_after_capacity():
    rl = RateLimiter(RateLimitConfig(enabled=True, default_rpm=3))
    results = [rl.check(_env()) for _ in range(5)]
    allowed = [r[0] for r in results]
    assert allowed == [True, True, True, False, False]
    # The blocked attempts return a useful retry_after
    info = results[-1][1]
    assert info["limit"] == 3
    assert info["remaining"] == 0
    assert info["retry_after"] >= 1


def test_per_path_rule_overrides_default():
    rl = RateLimiter(RateLimitConfig(
        enabled=True,
        default_rpm=10,
        path_rules={"/_fymo/remote/": 2},
    ))
    # The remote prefix gets only 2 tokens
    r1, _ = rl.check(_env("/_fymo/remote/abc/hello"))
    r2, _ = rl.check(_env("/_fymo/remote/abc/hello"))
    r3, _ = rl.check(_env("/_fymo/remote/abc/hello"))
    assert [r1, r2, r3] == [True, True, False]
    # A different path uses the default (10) bucket
    assert rl.check(_env("/posts"))[0] is True


def test_longest_prefix_wins():
    rl = RateLimiter(RateLimitConfig(
        enabled=True,
        default_rpm=100,
        path_rules={
            "/_fymo/": 50,
            "/_fymo/oauth/": 5,  # tighter for auth callbacks
        },
    ))
    # The /_fymo/oauth/ rule should override /_fymo/
    results = [rl.check(_env("/_fymo/oauth/google/callback"))[0] for _ in range(7)]
    # First 5 allowed, then blocked (longest-prefix rule of 5 wins, not 50)
    assert sum(results) == 5


def test_independent_buckets_per_ip():
    rl = RateLimiter(RateLimitConfig(enabled=True, default_rpm=1))
    assert rl.check(_env(ip="1.1.1.1"))[0] is True
    assert rl.check(_env(ip="1.1.1.1"))[0] is False
    # Different IP starts fresh
    assert rl.check(_env(ip="2.2.2.2"))[0] is True


def test_trust_proxy_uses_xff_first_hop():
    rl = RateLimiter(RateLimitConfig(
        enabled=True, default_rpm=1, trust_proxy=True,
    ))
    # XFF gets used in place of REMOTE_ADDR
    assert rl.check(_env(ip="10.0.0.1", xff="9.9.9.9"))[0] is True
    assert rl.check(_env(ip="10.0.0.1", xff="9.9.9.9"))[0] is False
    # Different forwarded IP gets a fresh bucket
    assert rl.check(_env(ip="10.0.0.1", xff="8.8.8.8"))[0] is True


def test_trust_proxy_ignores_xff_when_disabled():
    rl = RateLimiter(RateLimitConfig(
        enabled=True, default_rpm=1, trust_proxy=False,
    ))
    # XFF is ignored; REMOTE_ADDR is the key
    rl.check(_env(ip="10.0.0.1", xff="9.9.9.9"))
    # Second hit from same REMOTE_ADDR is blocked, regardless of XFF
    assert rl.check(_env(ip="10.0.0.1", xff="DIFFERENT"))[0] is False


# ---------------- Body cap ----------------


def test_body_limit_passes_under_cap():
    assert check_body_limit({"CONTENT_LENGTH": "500"}, max_bytes=1000) is True


def test_body_limit_rejects_over_cap():
    assert check_body_limit({"CONTENT_LENGTH": "1001"}, max_bytes=1000) is False


def test_body_limit_allows_when_content_length_missing():
    """Chunked transfer encoding has no Content-Length; we can't pre-check."""
    assert check_body_limit({}, max_bytes=10) is True


def test_body_limit_allows_when_content_length_garbage():
    assert check_body_limit({"CONTENT_LENGTH": "not-a-number"}, max_bytes=10) is True


# ---------------- Security headers ----------------


def test_default_headers_present_over_http():
    headers = security_headers_for({"wsgi.url_scheme": "http"})
    names = {k for k, _ in headers}
    assert "X-Content-Type-Options" in names
    assert "X-Frame-Options" in names
    assert "Referrer-Policy" in names
    assert "Permissions-Policy" in names
    # HSTS must NOT appear over plain http
    assert "Strict-Transport-Security" not in names


def test_hsts_added_only_over_https():
    headers = security_headers_for({"wsgi.url_scheme": "https"})
    names = {k for k, _ in headers}
    assert "Strict-Transport-Security" in names


def test_extra_headers_appended():
    headers = security_headers_for(
        {"wsgi.url_scheme": "http"},
        extra=[("Content-Security-Policy", "default-src 'self'")],
    )
    assert any(k == "Content-Security-Policy" for k, _ in headers)


def test_wrap_start_response_injects_headers():
    captured = []

    def sr(status, headers):
        captured.append((status, headers))

    wrapped = wrap_start_response(sr, {"wsgi.url_scheme": "http"})
    wrapped("200 OK", [("Content-Type", "text/plain")])
    status, headers = captured[0]
    keys = {k for k, _ in headers}
    assert "Content-Type" in keys
    assert "X-Content-Type-Options" in keys
    assert "X-Frame-Options" in keys


def test_wrap_does_not_overwrite_existing_header():
    """If the handler set a specific header, we don't clobber it."""
    captured = []
    def sr(status, headers):
        captured.append(headers)

    wrapped = wrap_start_response(sr, {"wsgi.url_scheme": "http"})
    wrapped("200 OK", [("X-Frame-Options", "SAMEORIGIN")])
    headers = captured[0]
    xfo_values = [v for k, v in headers if k == "X-Frame-Options"]
    assert xfo_values == ["SAMEORIGIN"]  # not DENY


def test_wrap_handles_2arg_start_response_signature():
    """Test stubs sometimes use the 2-arg signature; wrapper must adapt."""
    calls = []

    def sr_two_arg(status, headers):  # no exc_info
        calls.append((status, headers))

    wrapped = wrap_start_response(sr_two_arg, {"wsgi.url_scheme": "http"})
    # No TypeError when exc_info not passed
    wrapped("200 OK", [])
    assert len(calls) == 1


# ---------------- Settings loader ----------------


def test_settings_default_values_when_yaml_empty():
    s = MiddlewareSettings.from_yaml(limits={}, security={})
    assert s.rate_limit_config.enabled is True
    assert s.rate_limit_config.default_rpm == 60
    assert s.rate_limit_config.path_rules == {}
    assert s.rate_limit_config.trust_proxy is False
    assert s.max_body_bytes == DEFAULT_MAX_BODY_BYTES
    assert s.security_headers_enabled is True


def test_settings_from_yaml_complete():
    s = MiddlewareSettings.from_yaml(
        limits={
            "rate_limit": {
                "enabled": True,
                "requests_per_minute": 120,
                "paths": {"/_fymo/remote/": 30, "/_fymo/oauth/": 10},
                "trust_proxy": True,
            },
            "max_body_bytes": 5242880,
        },
        security={
            "headers": {
                "enabled": True,
                "extra": [["Content-Security-Policy", "default-src 'self'"]],
            },
        },
    )
    assert s.rate_limit_config.default_rpm == 120
    assert s.rate_limit_config.path_rules == {"/_fymo/remote/": 30, "/_fymo/oauth/": 10}
    assert s.rate_limit_config.trust_proxy is True
    assert s.max_body_bytes == 5242880
    assert s.extra_security_headers == [("Content-Security-Policy", "default-src 'self'")]


def test_settings_disabled_rate_limit():
    s = MiddlewareSettings.from_yaml(
        limits={"rate_limit": {"enabled": False}}, security={},
    )
    assert s.rate_limit_config.enabled is False


def test_settings_skips_malformed_path_rules():
    """A path rule with a non-int value gets skipped, not crash."""
    s = MiddlewareSettings.from_yaml(
        limits={"rate_limit": {"paths": {"/ok/": 30, "/bad/": "not-a-number"}}},
        security={},
    )
    assert s.rate_limit_config.path_rules == {"/ok/": 30}


def test_settings_skips_malformed_extra_headers():
    s = MiddlewareSettings.from_yaml(
        limits={},
        security={"headers": {"extra": [["ok", "val"], "garbage", ["one-elem-only"]]}},
    )
    assert s.extra_security_headers == [("ok", "val")]
