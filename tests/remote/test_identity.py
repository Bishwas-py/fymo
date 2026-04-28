"""Cookie-based identity: issue a uid on first POST, read it on subsequent."""
from http.cookies import SimpleCookie
from fymo.remote.identity import _ensure_uid, _UID_COOKIE


def _environ_with_cookie(value: str | None) -> dict:
    env = {"HTTP_COOKIE": "" if value is None else f"{_UID_COOKIE}={value}"}
    return env


def test_returns_existing_uid_when_present():
    env = _environ_with_cookie("u_existing")
    uid, set_cookie = _ensure_uid(env)
    assert uid == "u_existing"
    assert set_cookie is None


def test_issues_new_uid_when_absent():
    env = _environ_with_cookie(None)
    uid, set_cookie = _ensure_uid(env)
    assert uid.startswith("u_")
    assert len(uid) > 5
    assert set_cookie is not None
    assert _UID_COOKIE in set_cookie
    assert "Path=/" in set_cookie
    assert "Max-Age=" in set_cookie
    assert "SameSite=Lax" in set_cookie


def test_issues_unique_uids():
    a, _ = _ensure_uid({"HTTP_COOKIE": ""})
    b, _ = _ensure_uid({"HTTP_COOKIE": ""})
    assert a != b
