"""Password reset: request_password_reset issues a signed, single-use reset
token via the EmailSender seam (no email enumeration); reset_password
consumes it, sets a new password hash, and — because set_password_hash
already bumps session_epoch — implicitly revokes every outstanding session.

Covers three layers, mirroring tests/auth/test_email_verification.py:
  * fymo.auth.verify_token — make_reset_token / verify_reset_token (the
    "reset:" prefixed signed-token primitive, distinct from "verify:").
  * SqliteUserStore.set_reset_token / consume_reset_token — single-use
    enforcement on top of that primitive.
  * fymo.auth.remote — the wire-level contract: request_password_reset never
    reveals whether the email exists, reset_password flips the hash and
    kills old sessions.
"""
import base64
import io
import json
import sys
from pathlib import Path

import pytest

from fymo.auth import context as auth_context
from fymo.auth.email import EmailSender
from fymo.auth.providers.password import PasswordProvider
from fymo.auth.providers.registry import system_remote_modules
from fymo.auth.session import make_session_token
from fymo.auth.store import SqliteUserStore
from fymo.auth.verify_token import hash_token, make_reset_token, verify_reset_token
from fymo.remote import devalue, router as router_mod
from fymo.remote.discovery import _functions_hash
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _wire_secret():
    set_secret(b"x" * 32)


# --------------- fymo.auth.verify_token: make_reset_token / verify_reset_token ---------------


def test_reset_token_round_trips():
    token = make_reset_token(42, issued_at=1_000)
    assert verify_reset_token(token, now=1_100) == (42, 1_000)


def test_reset_token_rejects_forged_signature():
    token = make_reset_token(42, issued_at=1_000)
    uid, issued_at, _sig = token.split(".")
    forged = f"{uid}.{issued_at}.{'a' * 22}"
    assert verify_reset_token(forged, now=1_100) is None


def test_reset_token_rejects_expired():
    token = make_reset_token(42, issued_at=1_000)
    assert verify_reset_token(token, now=1_000 + 24 * 60 * 60 + 1) is None


def test_reset_token_and_verify_token_are_not_interchangeable():
    """A verify-email token must never work as a password-reset token, and
    vice versa — the "reset:" / "verify:" prefixes are baked into the
    signature itself, so swapping the payload's semantic role changes the
    HMAC input and breaks the signature check."""
    from fymo.auth.verify_token import make_verify_token

    verify_tok = make_verify_token(42, issued_at=1_000)
    # Re-sign the same (user_id, issued_at) shape as a reset token and prove
    # the two signatures differ, so one can't be presented as the other.
    reset_tok = make_reset_token(42, issued_at=1_000)
    assert verify_tok != reset_tok
    assert verify_reset_token(verify_tok, now=1_100) is None


# --------------- SqliteUserStore.set_reset_token / consume_reset_token ---------------


@pytest.fixture
def store(tmp_path: Path) -> SqliteUserStore:
    return SqliteUserStore(project_root=tmp_path)


def test_consume_valid_reset_token_returns_user_id(store):
    user = store.create("a@x.com", "oldhash")
    token = make_reset_token(user.id)
    store.set_reset_token(user.id, token)

    result = store.consume_reset_token(token)

    assert result == user.id


def test_consume_invalid_reset_token_returns_none(store):
    user = store.create("b@x.com", "oldhash")
    token = make_reset_token(user.id)
    store.set_reset_token(user.id, token)

    bogus = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert store.consume_reset_token(bogus) is None


def test_consume_reset_token_is_single_use(store):
    user = store.create("c@x.com", "oldhash")
    token = make_reset_token(user.id)
    store.set_reset_token(user.id, token)

    assert store.consume_reset_token(token) == user.id
    # Replaying the exact same token a second time must fail.
    assert store.consume_reset_token(token) is None


def test_set_reset_token_invalidates_previous_token(store):
    import time

    now = int(time.time())
    user = store.create("d@x.com", "oldhash")
    old_token = make_reset_token(user.id, issued_at=now - 100)
    store.set_reset_token(user.id, old_token)
    new_token = make_reset_token(user.id, issued_at=now)
    store.set_reset_token(user.id, new_token)

    assert store.consume_reset_token(old_token) is None
    assert store.consume_reset_token(new_token) == user.id


def test_consume_reset_token_for_unknown_user_returns_none(store):
    token = make_reset_token(999_999)
    assert store.consume_reset_token(token) is None


def test_migrates_db_created_before_reset_column_existed(tmp_path: Path):
    """A DB created before password_reset_token existed must gain it on open."""
    import sqlite3

    db_path = tmp_path / "app" / "data" / "auth.db"
    db_path.parent.mkdir(parents=True)
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(
        "CREATE TABLE fymo_users ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " email TEXT NOT NULL UNIQUE COLLATE NOCASE,"
        " password_hash TEXT, email_verified INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL, fymo_uid TEXT,"
        " session_epoch INTEGER NOT NULL DEFAULT 1);"
        "INSERT INTO fymo_users (email, password_hash, created_at)"
        " VALUES ('legacy@x.com', 'h', '2026-01-01T00:00:00+00:00');"
    )
    legacy.commit()
    legacy.close()

    store = SqliteUserStore(project_root=tmp_path)
    user = store.get_by_email("legacy@x.com")
    assert user is not None
    token = make_reset_token(user.id)
    store.set_reset_token(user.id, token)
    assert store.consume_reset_token(token) == user.id


# --------------- fymo.auth.remote wire-level contract ---------------


class SpyEmailSender(EmailSender):
    def __init__(self):
        self.sent = []
        self.reset_sent = []

    def send_verification(self, email: str, link: str) -> None:
        self.sent.append((email, link))

    def send_password_reset(self, email: str, link: str) -> None:
        self.reset_sent.append((email, link))


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch):
    store = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(store)
    sender = SpyEmailSender()
    auth_context.set_email_sender(sender)

    modules = system_remote_modules([PasswordProvider()])
    router_mod.set_system_modules(modules)
    auth_hash = _functions_hash(modules["auth"])

    monkeypatch.setattr(
        router_mod,
        "_resolve_module_for_hash",
        lambda h: "auth" if h == auth_hash else None,
    )
    yield store, auth_hash, sender
    router_mod.set_system_modules({})
    auth_context.set_email_sender(auth_context.LoggingEmailSender())


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

    def sr(status, headers):
        responses.append((status, headers))

    out = b"".join(router_mod.handle_remote(env, sr))
    return responses[0], json.loads(out)


def _extract_cookie(headers, name) -> str | None:
    for k, v in headers:
        if k.lower() == "set-cookie" and v.startswith(f"{name}="):
            return v.split(";", 1)[0]
    return None


def test_request_password_reset_for_known_email_sends_token(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["reset-me@x.com", "longpassword"])

    (_status, _headers), env = _call(h, "request_password_reset", ["reset-me@x.com"])

    assert env["type"] == "result", env
    assert devalue.parse(env["result"]) == {"ok": True}
    assert len(sender.reset_sent) == 1
    sent_email, link = sender.reset_sent[0]
    assert sent_email == "reset-me@x.com"
    assert "token=" in link


def test_request_password_reset_for_unknown_email_returns_same_ok_response(app_env):
    """Anti-enumeration: an unregistered email gets the exact same 200-shaped
    response as a registered one, and no email is sent."""
    store, h, sender = app_env

    (_status, _headers), env = _call(
        h, "request_password_reset", ["nobody-here@x.com"]
    )

    assert env["type"] == "result", env
    assert devalue.parse(env["result"]) == {"ok": True}
    assert sender.reset_sent == []


def test_reset_password_changes_hash_and_revokes_existing_sessions(app_env):
    store, h, sender = app_env
    (_status, headers), _env = _call(h, "signup", ["revoke@x.com", "originalpass"])
    old_session_cookie = _extract_cookie(headers, "fymo_session")
    assert old_session_cookie is not None

    _call(h, "request_password_reset", ["revoke@x.com"])
    _email, link = sender.reset_sent[0]
    token = link.split("token=", 1)[1]

    (_status, _headers), env = _call(h, "reset_password", [token, "newlongpassword"])
    assert env["type"] == "result", env
    assert devalue.parse(env["result"]) == {"ok": True}

    # New password works.
    (_status, _headers), login_env = _call(
        h, "login", ["revoke@x.com", "newlongpassword"]
    )
    assert login_env["type"] == "result", login_env

    # Old password no longer works.
    (_status, _headers), old_login_env = _call(
        h, "login", ["revoke@x.com", "originalpass"]
    )
    assert old_login_env["type"] == "error"
    assert old_login_env["error"] == "invalid_credentials"

    # The pre-existing session cookie (minted under the old epoch) is dead —
    # me() no longer authenticates it.
    (_status, _headers), me_env = _call(h, "me", [], cookies=old_session_cookie)
    assert me_env["type"] == "result"
    assert devalue.parse(me_env["result"]) is None


def test_reset_password_rejects_forged_token(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["forge-reset@x.com", "originalpass"])
    _call(h, "request_password_reset", ["forge-reset@x.com"])
    _email, link = sender.reset_sent[0]
    token = link.split("token=", 1)[1]
    uid, issued_at, _sig = token.split(".")
    forged = f"{uid}.{issued_at}.{'a' * 22}"

    (_status, _headers), env = _call(h, "reset_password", [forged, "newlongpassword"])

    assert env["type"] == "error"
    assert env["error"] == "invalid_token"
    # Old password still works — nothing changed.
    (_status, _headers), login_env = _call(
        h, "login", ["forge-reset@x.com", "originalpass"]
    )
    assert login_env["type"] == "result"


def test_reset_password_rejects_expired_token(app_env, monkeypatch):
    clock = {"now": 1_000_000}
    monkeypatch.setattr("time.time", lambda: clock["now"])

    store, h, sender = app_env
    _call(h, "signup", ["expire-reset@x.com", "originalpass"])
    _call(h, "request_password_reset", ["expire-reset@x.com"])
    _email, link = sender.reset_sent[0]
    token = link.split("token=", 1)[1]

    clock["now"] += 24 * 60 * 60 + 1

    (_status, _headers), env = _call(h, "reset_password", [token, "newlongpassword"])

    assert env["type"] == "error"
    assert env["error"] == "invalid_token"


def test_reset_password_token_is_single_use(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["once-reset@x.com", "originalpass"])
    _call(h, "request_password_reset", ["once-reset@x.com"])
    _email, link = sender.reset_sent[0]
    token = link.split("token=", 1)[1]

    (_status, _headers), first = _call(h, "reset_password", [token, "newlongpassword"])
    assert first["type"] == "result"

    (_status, _headers), second = _call(
        h, "reset_password", [token, "anothernewpass"]
    )
    assert second["type"] == "error"
    assert second["error"] == "invalid_token"


def test_reset_password_rejects_short_new_password(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["short-reset@x.com", "originalpass"])
    _call(h, "request_password_reset", ["short-reset@x.com"])
    _email, link = sender.reset_sent[0]
    token = link.split("token=", 1)[1]

    (_status, _headers), env = _call(h, "reset_password", [token, "short"])

    assert env["type"] == "error"
    assert env["error"] == "bad_input"
    # Token is not burned by a rejected password — it can still be used with
    # a valid password afterward.
    (_status, _headers), retry_env = _call(
        h, "reset_password", [token, "nowlongenough"]
    )
    assert retry_env["type"] == "result", retry_env
