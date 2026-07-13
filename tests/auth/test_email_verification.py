"""Email verification: signup issues a signed, single-use token via the
EmailSender seam; verify_email consumes it to flip email_verified to True.

Covers three layers:
  * fymo.auth.verify_token — the signed-token primitive (signature + expiry).
  * SqliteUserStore.set_verify_token / consume_verify_token — single-use
    enforcement (a matching row and a cleared hash) on top of that primitive.
  * fymo.auth.remote — the wire-level contract: signup sends via EmailSender,
    verify_email flips the flag, request_email_verification resends.
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
from fymo.auth.store import SqliteUserStore
from fymo.auth.verify_token import hash_token, make_verify_token, verify_verify_token
from fymo.remote import devalue, router as router_mod
from fymo.remote.discovery import _functions_hash
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _wire_secret():
    set_secret(b"x" * 32)


# --------------- fymo.auth.verify_token ---------------


def test_verify_token_round_trips():
    token = make_verify_token(42, issued_at=1_000)
    assert verify_verify_token(token, now=1_100) == (42, 1_000)


def test_verify_token_rejects_forged_signature():
    token = make_verify_token(42, issued_at=1_000)
    uid, issued_at, _sig = token.split(".")
    forged = f"{uid}.{issued_at}.{'a' * 22}"
    assert verify_verify_token(forged, now=1_100) is None


def test_verify_token_rejects_tampered_user_id():
    token = make_verify_token(42, issued_at=1_000)
    _uid, issued_at, sig = token.split(".")
    tampered = f"999.{issued_at}.{sig}"
    assert verify_verify_token(tampered, now=1_100) is None


def test_verify_token_rejects_expired():
    token = make_verify_token(42, issued_at=1_000)
    # default max_age is 24h; 24h + 1s later it must be rejected.
    assert verify_verify_token(token, now=1_000 + 24 * 60 * 60 + 1) is None


def test_verify_token_rejects_malformed():
    assert verify_verify_token("") is None
    assert verify_verify_token("not-a-token") is None
    assert verify_verify_token("1.2") is None


# --------------- SqliteUserStore.set_verify_token / consume_verify_token ---------------


@pytest.fixture
def store(tmp_path: Path) -> SqliteUserStore:
    return SqliteUserStore(project_root=tmp_path)


def test_consume_valid_token_marks_verified_and_returns_user_id(store):
    user = store.create("a@x.com", "h")
    assert user.email_verified is False
    token = make_verify_token(user.id)
    store.set_verify_token(user.id, token)

    result = store.consume_verify_token(token)

    assert result == user.id
    assert store.get_by_id(user.id).email_verified is True


def test_consume_invalid_token_returns_none_and_leaves_unverified(store):
    user = store.create("b@x.com", "h")
    token = make_verify_token(user.id)
    store.set_verify_token(user.id, token)

    bogus = token[:-1] + ("a" if token[-1] != "a" else "b")
    result = store.consume_verify_token(bogus)

    assert result is None
    assert store.get_by_id(user.id).email_verified is False


def test_consume_token_is_single_use(store):
    user = store.create("c@x.com", "h")
    token = make_verify_token(user.id)
    store.set_verify_token(user.id, token)

    assert store.consume_verify_token(token) == user.id
    # Replaying the exact same token a second time must fail — the hash was
    # cleared on first consumption.
    assert store.consume_verify_token(token) is None


def test_set_verify_token_invalidates_previous_token(store):
    import time

    now = int(time.time())
    user = store.create("d@x.com", "h")
    old_token = make_verify_token(user.id, issued_at=now - 100)
    store.set_verify_token(user.id, old_token)
    new_token = make_verify_token(user.id, issued_at=now)
    store.set_verify_token(user.id, new_token)

    # The superseded token no longer matches the stored hash.
    assert store.consume_verify_token(old_token) is None
    assert store.get_by_id(user.id).email_verified is False
    # The latest token still works.
    assert store.consume_verify_token(new_token) == user.id


def test_consume_token_for_unknown_user_returns_none(store):
    token = make_verify_token(999_999)
    assert store.consume_verify_token(token) is None


def test_migrates_db_created_before_verify_columns_existed(tmp_path: Path):
    """A DB created before these columns existed must gain them on open."""
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
    token = make_verify_token(user.id)
    store.set_verify_token(user.id, token)
    assert store.consume_verify_token(token) == user.id
    assert store.get_by_id(user.id).email_verified is True


# --------------- fymo.auth.remote wire-level contract ---------------


class SpyEmailSender(EmailSender):
    def __init__(self):
        self.sent = []

    def send_verification(self, email: str, link: str) -> None:
        self.sent.append((email, link))


class RaisingEmailSender(EmailSender):
    """Simulates a real (non-logging) sender hitting a transient failure,
    e.g. an SMTP timeout — used to prove signup is best-effort on delivery."""

    def send_verification(self, email: str, link: str) -> None:
        raise RuntimeError("smtp timeout")


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


def test_signup_creates_user_unverified_and_invokes_email_sender(app_env):
    store, h, sender = app_env
    (_status, _headers), env = _call(h, "signup", ["verify-me@x.com", "longpassword"])
    assert env["type"] == "result"
    user = devalue.parse(env["result"])
    assert user["email_verified"] is False

    assert len(sender.sent) == 1
    sent_email, link = sender.sent[0]
    assert sent_email == "verify-me@x.com"
    assert "token=" in link


def test_verify_email_flips_flag_via_router(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["flip@x.com", "longpassword"])
    _email, link = sender.sent[0]
    token = link.split("token=", 1)[1]

    (_status, _headers), env = _call(h, "verify_email", [token])

    assert env["type"] == "result", env
    result = devalue.parse(env["result"])
    assert result["email_verified"] is True
    user = store.get_by_email("flip@x.com")
    assert user.email_verified is True


def test_verify_email_rejects_invalid_token_and_leaves_unverified(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["bad-token@x.com", "longpassword"])

    (_status, _headers), env = _call(h, "verify_email", ["not-a-real-token"])

    assert env["type"] == "error"
    assert env["error"] == "invalid_token"
    user = store.get_by_email("bad-token@x.com")
    assert user.email_verified is False


def test_verify_email_rejects_forged_signature(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["forge@x.com", "longpassword"])
    _email, link = sender.sent[0]
    token = link.split("token=", 1)[1]
    uid, issued_at, _sig = token.split(".")
    forged = f"{uid}.{issued_at}.{'a' * 22}"

    (_status, _headers), env = _call(h, "verify_email", [forged])

    assert env["type"] == "error"
    assert env["error"] == "invalid_token"
    assert store.get_by_email("forge@x.com").email_verified is False


def test_verify_email_token_is_single_use_over_the_wire(app_env):
    store, h, sender = app_env
    _call(h, "signup", ["once@x.com", "longpassword"])
    _email, link = sender.sent[0]
    token = link.split("token=", 1)[1]

    (_status, _headers), first = _call(h, "verify_email", [token])
    assert first["type"] == "result"

    (_status, _headers), second = _call(h, "verify_email", [token])
    assert second["type"] == "error"
    assert second["error"] == "invalid_token"


def test_request_email_verification_requires_auth(app_env):
    _store, h, _sender = app_env
    (_status, _headers), env = _call(h, "request_email_verification", [])
    assert env["type"] == "error"
    assert env["error"] == "unauthenticated"


def test_request_email_verification_resends_and_invalidates_old_token(app_env, monkeypatch):
    # Pin the clock so the two issued-at seconds are guaranteed to differ —
    # otherwise a fast test run could mint two identical tokens (same
    # user_id + same second) and this test would spuriously fail.
    clock = {"now": 1_000_000}
    monkeypatch.setattr("time.time", lambda: clock["now"])

    store, h, sender = app_env
    (_status, headers), _env = _call(h, "signup", ["resend@x.com", "longpassword"])
    session_cookie = _extract_cookie(headers, "fymo_session")
    _first_email, first_link = sender.sent[0]
    first_token = first_link.split("token=", 1)[1]

    clock["now"] += 10
    (_status, _headers), env = _call(
        h, "request_email_verification", [], cookies=session_cookie
    )
    assert env["type"] == "result"
    assert devalue.parse(env["result"])["ok"] is True

    assert len(sender.sent) == 2
    _second_email, second_link = sender.sent[1]
    second_token = second_link.split("token=", 1)[1]
    assert second_token != first_token

    # The old token was superseded and no longer verifies.
    (_status, _headers), old_result = _call(h, "verify_email", [first_token])
    assert old_result["type"] == "error"

    (_status, _headers), new_result = _call(h, "verify_email", [second_token])
    assert new_result["type"] == "result"
    assert store.get_by_email("resend@x.com").email_verified is True


def test_signup_succeeds_even_if_email_sender_raises(app_env):
    """Robustness: the account is already committed to the DB by the time
    the verification email is sent. If a real EmailSender raises (SMTP
    timeout, provider outage, ...), signup must still succeed and return a
    session — the send is best-effort, not part of signup's success path."""
    store, h, spy_sender = app_env
    auth_context.set_email_sender(RaisingEmailSender())
    try:
        (_status, headers), env = _call(h, "signup", ["raises@x.com", "longpassword"])
    finally:
        # Restore the spy so app_env's own teardown (and any assertions a
        # later test in the same session might make) see the expected type.
        auth_context.set_email_sender(spy_sender)

    assert env["type"] == "result", env
    user = devalue.parse(env["result"])
    assert user["email_verified"] is False
    assert _extract_cookie(headers, "fymo_session") is not None

    stored = store.get_by_email("raises@x.com")
    assert stored is not None
    assert stored.email_verified is False


def test_verify_email_rejects_expired_token_via_router(app_env, monkeypatch):
    """Expiry is unit-tested at the verify_token level in
    test_session-style tests; this drives the same case end-to-end through
    handle_remote to prove the router surfaces it as invalid_token and never
    flips email_verified."""
    clock = {"now": 1_000_000}
    monkeypatch.setattr("time.time", lambda: clock["now"])

    store, h, sender = app_env
    _call(h, "signup", ["expires@x.com", "longpassword"])
    _email, link = sender.sent[0]
    token = link.split("token=", 1)[1]

    # Past the token's max age (24h) since it was issued.
    clock["now"] += 24 * 60 * 60 + 1

    (_status, _headers), env = _call(h, "verify_email", [token])

    assert env["type"] == "error"
    assert env["error"] == "invalid_token"
    assert store.get_by_email("expires@x.com").email_verified is False


def test_verify_email_only_flips_the_matching_user(app_env):
    """Cross-user isolation: user A's token must never verify user B, even
    though both tokens are issued around the same time and share the same
    signing secret."""
    store, h, sender = app_env
    _call(h, "signup", ["user-a@x.com", "longpassword"])
    _call(h, "signup", ["user-b@x.com", "longpassword"])
    _email_a, link_a = sender.sent[0]
    _email_b, _link_b = sender.sent[1]
    token_a = link_a.split("token=", 1)[1]

    (_status, _headers), env = _call(h, "verify_email", [token_a])

    assert env["type"] == "result", env
    assert store.get_by_email("user-a@x.com").email_verified is True
    assert store.get_by_email("user-b@x.com").email_verified is False
