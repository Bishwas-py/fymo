"""Email-enumeration timing side-channel: `login` must cost roughly the same
whether the email is registered or not.

Before the fix, `login` short-circuited on `user is None or password_hash is
None` without ever calling `verify_password` — so an unknown email skipped
the ~50ms scrypt verify that a known email (with a wrong password) always
pays. That timing gap lets an attacker enumerate registered emails even
though the error message is identical in both cases.

Rather than asserting wall-clock timing (flaky), this asserts the behavioral
proxy the fix introduces: `verify_password` is invoked against a decoy hash
on the user-missing path too, so both branches always do one scrypt verify.
"""
import base64
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

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


def test_login_runs_scrypt_verify_even_when_email_is_unknown(app_env):
    """The core enumeration-timing test: `verify_password` must be called on
    the user-missing path, not just the wrong-password path. If this is
    False, login returns instantly for unknown emails while paying ~50ms of
    scrypt for known ones — an observable timing side-channel."""
    _, h = app_env
    with patch("fymo.auth.remote.verify_password", return_value=False) as spy:
        (_, _), env = _call(h, "login", ["nobody-ever-signed-up@x.com", "whatever1"])
        assert env["type"] == "error"
        assert env["error"] == "invalid_credentials"
        assert spy.called, (
            "verify_password was not called on the unknown-email path; "
            "login short-circuits before doing scrypt work, leaking email "
            "existence via response timing"
        )


def test_login_still_rejects_wrong_password_for_known_email(app_env):
    """Sanity check: the decoy-verify addition must not weaken the real check."""
    _, h = app_env
    _call(h, "signup", ["known@x.com", "correct-password"])
    (_, _), env = _call(h, "login", ["known@x.com", "wrong-password"])
    assert env["type"] == "error"
    assert env["error"] == "invalid_credentials"


def test_login_still_succeeds_with_correct_password(app_env):
    """Sanity check: the decoy path must not interfere with real logins."""
    _, h = app_env
    _call(h, "signup", ["good@x.com", "correct-password"])
    (_, _), env = _call(h, "login", ["good@x.com", "correct-password"])
    assert env["type"] == "result"
    user = devalue.parse(env["result"])
    assert user["email"] == "good@x.com"
