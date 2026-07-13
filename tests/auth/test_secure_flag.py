"""Session cookie's Secure flag must reflect the *true* request scheme.

Behind a TLS-terminating reverse proxy, `wsgi.url_scheme` reads "http" even
though the client connected over https — so without honoring
`X-Forwarded-Proto`, the session cookie ships without `Secure`. Fix: honor
that header, but only when `trust_proxy` is enabled (same trust boundary as
`RateLimitConfig.trust_proxy` / `X-Forwarded-For`), so a client can't spoof
`X-Forwarded-Proto: https` over plain http to fake a secure context.
"""
import pytest

from fymo.auth.context import (
    consume_pending_cookies,
    end_auth_scope,
    queue_session_cookie,
    start_auth_scope,
)
from fymo.auth.remote import _environ_from_event
from fymo.remote.context import request_scope, set_trust_proxy
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _install_secret():
    set_secret(b"x" * 32)


@pytest.fixture(autouse=True)
def _reset_trust_proxy():
    yield
    set_trust_proxy(False)


def _cookie_for(environ: dict, *, trust_proxy: bool) -> str:
    """Drive the exact path signup/login use: request_scope -> _environ_from_event
    -> queue_session_cookie -> Set-Cookie header."""
    set_trust_proxy(trust_proxy)
    token = start_auth_scope()
    try:
        with request_scope(uid="u_test", environ=environ):
            queue_session_cookie(1, 0, environ=_environ_from_event())
        cookies = consume_pending_cookies()
        assert len(cookies) == 1
        return cookies[0]
    finally:
        end_auth_scope(token)


def test_trust_proxy_honors_forwarded_proto_for_secure_flag():
    """The core fix: trust_proxy on + X-Forwarded-Proto: https must set
    Secure even though wsgi.url_scheme is http (TLS terminated upstream)."""
    environ = {
        "wsgi.url_scheme": "http",
        "HTTP_X_FORWARDED_PROTO": "https",
        "REMOTE_ADDR": "10.0.0.1",
    }
    cookie = _cookie_for(environ, trust_proxy=True)
    assert "Secure" in cookie


def test_spoofed_forwarded_proto_ignored_without_trust_proxy():
    """Anti-spoof: without trust_proxy, an attacker-supplied
    X-Forwarded-Proto: https over real plain http must NOT set Secure."""
    environ = {
        "wsgi.url_scheme": "http",
        "HTTP_X_FORWARDED_PROTO": "https",
        "REMOTE_ADDR": "10.0.0.1",
    }
    cookie = _cookie_for(environ, trust_proxy=False)
    assert "Secure" not in cookie


def test_https_scheme_still_secure_without_trust_proxy():
    """Existing behavior preserved: direct https always gets Secure,
    trust_proxy or not."""
    environ = {"wsgi.url_scheme": "https", "REMOTE_ADDR": "10.0.0.1"}
    assert "Secure" in _cookie_for(environ, trust_proxy=False)
    assert "Secure" in _cookie_for(environ, trust_proxy=True)


def test_plain_http_without_proxy_has_no_secure():
    """Existing dev behavior preserved: plain http, no proxy, no Secure."""
    environ = {"wsgi.url_scheme": "http", "REMOTE_ADDR": "10.0.0.1"}
    assert "Secure" not in _cookie_for(environ, trust_proxy=False)


def test_trust_proxy_on_without_forwarded_header_falls_back_to_wsgi_scheme():
    """trust_proxy enabled but no X-Forwarded-Proto present: fall back to
    wsgi.url_scheme rather than assuming https."""
    environ = {"wsgi.url_scheme": "http", "REMOTE_ADDR": "10.0.0.1"}
    assert "Secure" not in _cookie_for(environ, trust_proxy=True)
