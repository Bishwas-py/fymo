"""Cookie-based identity: HMAC-signed uid round-trip + tamper rejection."""
import pytest
from fymo.remote.identity import _ensure_uid, _UID_COOKIE, set_secret, _sign


@pytest.fixture(autouse=True)
def _install_secret():
    """Every test in this module runs with a deterministic test secret."""
    set_secret(b"x" * 32)


def _environ_with_cookie(value: str | None) -> dict:
    return {"HTTP_COOKIE": "" if value is None else f"{_UID_COOKIE}={value}"}


def test_issues_new_signed_uid_when_absent():
    """Fresh request gets a new uid + Set-Cookie header containing the signed token."""
    uid, set_cookie = _ensure_uid({"HTTP_COOKIE": ""})
    assert uid.startswith("u_")
    assert set_cookie is not None
    # The cookie value should be `<uid>.<sig>`
    assert f"{_UID_COOKIE}={uid}." in set_cookie
    assert "Path=/" in set_cookie
    assert "Max-Age=" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "HttpOnly" in set_cookie


def test_returns_existing_uid_when_signature_valid():
    """A correctly-signed cookie is honored; no Set-Cookie is reissued."""
    uid = "u_existinguid"
    signed = f"{uid}.{_sign(uid)}"
    env = _environ_with_cookie(signed)
    returned, set_cookie = _ensure_uid(env)
    assert returned == uid
    assert set_cookie is None


def test_rejects_unsigned_legacy_cookie():
    """A cookie missing the .signature suffix is treated as if absent."""
    env = _environ_with_cookie("u_unsigned_legacy")
    uid, set_cookie = _ensure_uid(env)
    assert uid != "u_unsigned_legacy"
    assert set_cookie is not None  # reissued


def test_rejects_tampered_uid():
    """An attacker swapping the uid but keeping someone else's signature must be rejected."""
    real = "u_realuser"
    sig = _sign(real)
    forged = f"u_admin.{sig}"  # same sig, different uid
    env = _environ_with_cookie(forged)
    uid, set_cookie = _ensure_uid(env)
    assert uid != "u_admin"
    assert uid.startswith("u_")
    assert set_cookie is not None  # reissued


def test_rejects_truncated_signature():
    env = _environ_with_cookie("u_someuid.tooshort")
    uid, set_cookie = _ensure_uid(env)
    assert uid != "u_someuid"
    assert set_cookie is not None


def test_rejects_signature_under_different_secret():
    """A cookie signed under a different secret must not validate."""
    other_sig = "AAAAAAAAAAAAAAAAAAAAAA"  # 22 chars but wrong
    env = _environ_with_cookie(f"u_someuid.{other_sig}")
    uid, set_cookie = _ensure_uid(env)
    assert uid != "u_someuid"
    assert set_cookie is not None


def test_issues_unique_uids():
    a, _ = _ensure_uid({"HTTP_COOKIE": ""})
    b, _ = _ensure_uid({"HTTP_COOKIE": ""})
    assert a != b


def test_set_secret_rejects_short_secret():
    with pytest.raises(ValueError):
        set_secret(b"too short")
