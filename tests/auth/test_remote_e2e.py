"""End-to-end: signup → login → me → logout via /_fymo/remote/<hash>/<fn>.

Uses the actual remote-function router so the test doubles as a contract
check on the new wire-level cookie threading (Set-Cookie from queued auth
state).
"""
import base64
import io
import json
import sys
from pathlib import Path

import pytest

from fymo.auth import context as auth_context
from fymo.auth.providers.password import PasswordProvider
from fymo.auth.providers.registry import system_remote_modules
from fymo.auth.store import SqliteUserStore
from fymo.remote import devalue, router as router_mod
from fymo.remote.discovery import _functions_hash
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _wire_secret():
    set_secret(b"x" * 32)


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch):
    """Install a fresh UserStore and wire the auth module the way FymoApp does:
    register the password provider's remote functions with the router."""
    store = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(store)

    modules = system_remote_modules([PasswordProvider()])
    router_mod.set_system_modules(modules)
    auth_hash = _functions_hash(modules["auth"])

    monkeypatch.setattr(
        router_mod,
        "_resolve_module_for_hash",
        lambda h: "auth" if h == auth_hash else None,
    )
    yield store, auth_hash
    router_mod.set_system_modules({})


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _call(hash_: str, fn: str, args: list, cookies: str = "", scheme: str = "http"):
    body = json.dumps({"payload": _b64url(devalue.stringify(args))}).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"/_fymo/remote/{hash_}/{fn}",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "HTTP_HOST": "x",
        "HTTP_ORIGIN": f"{scheme}://x",
        "wsgi.url_scheme": scheme,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": sys.stderr,
    }
    responses = []
    def sr(status, headers): responses.append((status, headers))
    out = b"".join(router_mod.handle_remote(env, sr))
    return responses[0], json.loads(out)


def _extract_cookie(headers, name) -> str | None:
    for k, v in headers:
        if k.lower() == "set-cookie" and v.startswith(f"{name}="):
            return v.split(";", 1)[0]  # `name=value`
    return None


def test_signup_creates_user_and_returns_session_cookie(app_env):
    store, h = app_env
    (status, headers), env = _call(h, "signup", ["alice@example.com", "longpassword"])
    assert status.startswith("200"), env
    assert env["type"] == "result"
    user = devalue.parse(env["result"])
    assert user["email"] == "alice@example.com"
    assert user["id"] > 0
    # password_hash and fymo_uid not exposed
    assert "password_hash" not in user
    assert "fymo_uid" not in user
    # Set-Cookie carries the signed session
    session_cookie = _extract_cookie(headers, "fymo_session")
    assert session_cookie is not None
    assert session_cookie.startswith(f"fymo_session={user['id']}.")


def test_signup_rejects_short_password(app_env):
    _, h = app_env
    (status, _), env = _call(h, "signup", ["x@x.com", "short"])
    assert env["type"] == "error"
    assert env["status"] == 400


def test_signup_duplicate_email_returns_409(app_env):
    _, h = app_env
    _call(h, "signup", ["dup@x.com", "longpassword"])
    (status, _), env = _call(h, "signup", ["dup@x.com", "anotherlongpassword"])
    assert env["type"] == "error"
    assert env["status"] == 409


def test_login_returns_session_when_correct(app_env):
    _, h = app_env
    _call(h, "signup", ["bob@x.com", "longpassword"])
    (status, headers), env = _call(h, "login", ["bob@x.com", "longpassword"])
    assert env["type"] == "result"
    user = devalue.parse(env["result"])
    assert user["email"] == "bob@x.com"
    assert _extract_cookie(headers, "fymo_session") is not None


def test_login_wrong_password_returns_401_invalid_credentials(app_env):
    _, h = app_env
    _call(h, "signup", ["c@x.com", "longpassword"])
    (status, headers), env = _call(h, "login", ["c@x.com", "WRONGpassword"])
    assert env["type"] == "error"
    assert env["status"] == 401
    assert env["error"] == "invalid_credentials"
    assert _extract_cookie(headers, "fymo_session") is None


def test_login_unknown_email_returns_same_error_as_wrong_password(app_env):
    """Account enumeration: identical response for "no user" vs "bad password"."""
    _, h = app_env
    (_, _), env = _call(h, "login", ["never-signed-up@x.com", "anything"])
    assert env["type"] == "error"
    assert env["status"] == 401
    assert env["error"] == "invalid_credentials"


def test_me_returns_null_without_session(app_env):
    _, h = app_env
    (_, _), env = _call(h, "me", [])
    assert env["type"] == "result"
    assert devalue.parse(env["result"]) is None


def test_me_returns_user_with_valid_session(app_env):
    _, h = app_env
    (_, headers), _ = _call(h, "signup", ["d@x.com", "longpassword"])
    session_cookie = _extract_cookie(headers, "fymo_session")

    (_, _), env = _call(h, "me", [], cookies=session_cookie)
    assert env["type"] == "result"
    user = devalue.parse(env["result"])
    assert user is not None
    assert user["email"] == "d@x.com"


def test_logout_clears_session_cookie(app_env):
    _, h = app_env
    (_, signup_headers), _ = _call(h, "signup", ["e@x.com", "longpassword"])
    session_cookie = _extract_cookie(signup_headers, "fymo_session")

    (_, logout_headers), env = _call(h, "logout", [], cookies=session_cookie)
    assert env["type"] == "result"
    cleared = _extract_cookie(logout_headers, "fymo_session")
    assert cleared is not None
    # Max-Age=0 is the clearing pattern
    full = next(v for k, v in logout_headers if k.lower() == "set-cookie" and "fymo_session=" in v)
    assert "Max-Age=0" in full


def test_logout_invalidates_a_captured_session_cookie(app_env):
    """Server-side revocation: after logout, the *same* cookie value an
    attacker might have captured must no longer authenticate — clearing the
    browser's copy is not enough."""
    _, h = app_env
    (_, headers), _ = _call(h, "signup", ["g@x.com", "longpassword"])
    captured = _extract_cookie(headers, "fymo_session")

    # The captured cookie works before logout.
    (_, _), before = _call(h, "me", [], cookies=captured)
    assert devalue.parse(before["result"]) is not None

    # User logs out (their browser sends the cookie).
    _call(h, "logout", [], cookies=captured)

    # Replaying the captured cookie must now be rejected.
    (_, _), after = _call(h, "me", [], cookies=captured)
    assert devalue.parse(after["result"]) is None, "captured cookie still valid after logout"


def test_password_change_invalidates_existing_sessions(app_env):
    """Changing the password must revoke sessions issued under the old one."""
    store, h = app_env
    (_, headers), user_env = _call(h, "signup", ["hh@x.com", "longpassword"])
    captured = _extract_cookie(headers, "fymo_session")
    user_id = devalue.parse(user_env["result"])["id"]

    # Session valid before the password change.
    (_, _), before = _call(h, "me", [], cookies=captured)
    assert devalue.parse(before["result"]) is not None

    from fymo.auth.passwords import hash_password
    store.set_password_hash(user_id, hash_password("a-brand-new-password"))

    (_, _), after = _call(h, "me", [], cookies=captured)
    assert devalue.parse(after["result"]) is None, "old session survived a password change"


def test_signup_attaches_current_uid_to_user(app_env):
    """Anonymous activity (reactions, comments) becomes claimed on signup."""
    store, h = app_env
    # First request: get a fymo_uid cookie back.
    (_, headers), _ = _call(h, "me", [])
    uid_cookie = _extract_cookie(headers, "fymo_uid")
    assert uid_cookie is not None

    # Reuse that uid when signing up.
    (_, _), env = _call(h, "signup", ["f@x.com", "longpassword"], cookies=uid_cookie)
    user = devalue.parse(env["result"])
    # The stored uid is the verified, unsigned portion (the signature is stripped
    # by _ensure_uid before the request scope sees it).
    full_value = uid_cookie.split("=", 1)[1]
    expected_uid = full_value.rsplit(".", 1)[0]  # drop the .<sig> suffix
    stored = store.get_by_id(user["id"])
    assert stored.fymo_uid == expected_uid


def test_require_auth_returns_401_envelope_without_session(app_env, monkeypatch):
    """A user-authored remote function decorated with @require_auth must
    return the unauthenticated envelope when no session is present."""
    _, h = app_env

    # Register a @require_auth function under the `auth` module the way a
    # provider would expose it.
    from fymo.auth.context import require_auth

    @require_auth
    def secret_thing() -> str:  # type: ignore[no-redef]
        return "you shouldn't see this"

    router_mod.set_system_modules({"auth": {"secret_thing": secret_thing}})

    (_, _), env = _call(h, "secret_thing", [])
    assert env["type"] == "error"
    assert env["status"] == 401
    assert env["error"] == "unauthenticated"
