"""Public response-cookie seam for remote functions (issue #80 phase 3).

App-owned auth code (the `fymo generate auth` output) needs to queue a
session Set-Cookie from inside a remote function. The legacy queue helpers
in fymo.auth.context are private or User-shaped, so fymo.remote grows a
small public pair: set_cookie() and clear_cookie(). They queue onto the
same pending-cookie scope the remote router already drains.
"""
import pytest

from fymo.auth.context import consume_pending_cookies, end_auth_scope, start_auth_scope
from fymo.remote import clear_cookie, set_cookie
from fymo.remote.context import request_scope


@pytest.fixture
def cookie_scope():
    token = start_auth_scope()
    with request_scope(uid="u_anon", environ={}):
        yield
    end_auth_scope(token)


@pytest.fixture
def https_cookie_scope():
    token = start_auth_scope()
    with request_scope(uid="u_anon", environ={"wsgi.url_scheme": "https"}):
        yield
    end_auth_scope(token)


def test_set_cookie_queues_header(cookie_scope):
    set_cookie("session", "tok123")
    cookies = consume_pending_cookies()
    assert len(cookies) == 1
    header = cookies[0]
    assert header.startswith("session=tok123")
    assert "Path=/" in header
    assert "SameSite=Lax" in header
    assert "HttpOnly" in header


def test_set_cookie_http_only_default_and_opt_out(cookie_scope):
    set_cookie("a", "1")
    set_cookie("b", "2", http_only=False)
    a, b = consume_pending_cookies()
    assert "HttpOnly" in a
    assert "HttpOnly" not in b


def test_set_cookie_max_age(cookie_scope):
    set_cookie("session", "tok", max_age=3600)
    (header,) = consume_pending_cookies()
    assert "Max-Age=3600" in header


def test_set_cookie_no_max_age_by_default(cookie_scope):
    set_cookie("session", "tok")
    (header,) = consume_pending_cookies()
    assert "Max-Age" not in header


def test_set_cookie_secure_follows_resolved_scheme(https_cookie_scope):
    set_cookie("session", "tok")
    (header,) = consume_pending_cookies()
    assert "Secure" in header


def test_set_cookie_not_secure_on_http(cookie_scope):
    set_cookie("session", "tok")
    (header,) = consume_pending_cookies()
    assert "Secure" not in header


def test_set_cookie_secure_explicit_override(cookie_scope):
    set_cookie("session", "tok", secure=True)
    (header,) = consume_pending_cookies()
    assert "Secure" in header


def test_set_cookie_same_site_variants(cookie_scope):
    set_cookie("a", "1", same_site="Strict")
    (header,) = consume_pending_cookies()
    assert "SameSite=Strict" in header


def test_set_cookie_rejects_bad_same_site(cookie_scope):
    with pytest.raises(ValueError):
        set_cookie("a", "1", same_site="Sideways")


def test_set_cookie_rejects_invalid_name(cookie_scope):
    with pytest.raises(ValueError):
        set_cookie("bad name", "v")
    with pytest.raises(ValueError):
        set_cookie("bad;name", "v")
    with pytest.raises(ValueError):
        set_cookie("", "v")


def test_set_cookie_rejects_invalid_value(cookie_scope):
    with pytest.raises(ValueError):
        set_cookie("n", "a;b")
    with pytest.raises(ValueError):
        set_cookie("n", "a b")
    with pytest.raises(ValueError):
        set_cookie("n", "a\nb")


def test_clear_cookie_expires_immediately(cookie_scope):
    clear_cookie("session")
    (header,) = consume_pending_cookies()
    assert header.startswith("session=")
    assert "Max-Age=0" in header


def test_set_cookie_outside_scope_raises():
    with pytest.raises(RuntimeError) as exc_info:
        set_cookie("session", "tok")
    assert "remote" in str(exc_info.value)


def test_multiple_cookies_queue_in_order(cookie_scope):
    set_cookie("a", "1")
    set_cookie("b", "2")
    headers = consume_pending_cookies()
    assert headers[0].startswith("a=1")
    assert headers[1].startswith("b=2")
