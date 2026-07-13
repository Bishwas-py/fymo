"""Signed fymo_session cookie round-trip + tamper rejection."""
import pytest
from fymo.auth.session import (
    make_session_token,
    verify_session_token,
    build_set_cookie,
    build_clear_cookie,
    read_session_cookie,
    _sign,
)
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _install_secret():
    set_secret(b"x" * 32)


def test_round_trip():
    token = make_session_token(42, epoch=3)
    assert verify_session_token(token) == (42, 3)


def test_tampered_user_id_rejected():
    real = make_session_token(42, epoch=1)
    # Swap the uid but keep the rest of the token (incl. signature).
    _, issued, epoch, sig = real.split(".")
    forged = f"99.{issued}.{epoch}.{sig}"
    assert verify_session_token(forged) is None


def test_tampered_epoch_rejected():
    """Epoch is signed, so an attacker can't downgrade to an older epoch to
    dodge a revocation."""
    real = make_session_token(42, epoch=5)
    uid, issued, _, sig = real.split(".")
    forged = f"{uid}.{issued}.1.{sig}"
    assert verify_session_token(forged) is None


def test_expired_token_rejected():
    token = make_session_token(42, epoch=1, issued_at=1_000)
    # now is well past issued_at + max_age
    assert verify_session_token(token, now=1_000 + 8 * 24 * 3600) is None


def test_unexpired_token_accepted():
    token = make_session_token(42, epoch=1, issued_at=1_000)
    assert verify_session_token(token, now=1_000 + 60) == (42, 1)


def test_unsigned_token_rejected():
    assert verify_session_token("42") is None
    assert verify_session_token("42.abc") is None  # old 2-part shape no longer valid


def test_garbage_token_rejected():
    assert verify_session_token("not-even-close") is None
    assert verify_session_token("") is None
    assert verify_session_token(".abc") is None


def test_negative_user_id_rejected():
    """Token format requires positive uid; a signed -1 token must not round-trip."""
    forged = f"-1.1000.1.{_sign(-1, 1000, 1)}"
    assert verify_session_token(forged) is None


def test_make_token_rejects_invalid_user_id():
    with pytest.raises(ValueError):
        make_session_token(0, epoch=1)
    with pytest.raises(ValueError):
        make_session_token(-1, epoch=1)


def test_set_cookie_includes_secure_only_on_https():
    cookie_http = build_set_cookie("42.xyz", environ={"wsgi.url_scheme": "http"})
    assert "Secure" not in cookie_http
    cookie_https = build_set_cookie("42.xyz", environ={"wsgi.url_scheme": "https"})
    assert "Secure" in cookie_https


def test_clear_cookie_zeros_max_age():
    cookie = build_clear_cookie(environ={"wsgi.url_scheme": "http"})
    assert "Max-Age=0" in cookie
    assert "fymo_session=" in cookie


def test_read_session_cookie_returns_user_id_when_valid():
    token = make_session_token(7, epoch=1)
    env = {"HTTP_COOKIE": f"fymo_session={token}"}
    assert read_session_cookie(env) == (7, 1)


def test_read_session_cookie_returns_none_when_missing():
    assert read_session_cookie({}) is None
    assert read_session_cookie({"HTTP_COOKIE": ""}) is None
    assert read_session_cookie({"HTTP_COOKIE": "other=stuff"}) is None
