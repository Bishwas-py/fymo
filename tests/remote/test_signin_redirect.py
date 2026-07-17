"""$remote 401 -> signin redirect, server half (issue #80 phase 4).

The signin path has a single source of truth: the route named `signin`
in fymo.yml. The server (which knows it) attaches it to the 401
unauthenticated envelope; the generated $remote client (which knows the
browser's current location) follows it with ?next=. The client never
embeds the path at build time.

Only the `unauthenticated` code (AuthRequired, "you must sign in to call
this") gets the field. A plain Unauthorized (e.g. wrong password from the
signin page's own login remote) must NOT trigger a redirect back to
signin, or the error message would be lost to a pointless navigation.
"""
import base64
import io
import json
import sys

import pytest

from fymo.remote import devalue
from fymo.remote.router import (
    _remote_error_payload,
    handle_remote,
    set_signin_path,
)
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _reset_seams():
    set_secret(b"test-secret-16-bytes-long")
    yield
    set_signin_path(None)


def test_unauthenticated_envelope_carries_signin_path():
    from fymo.auth.context import AuthRequired

    set_signin_path("/signin")
    payload = _remote_error_payload(AuthRequired())
    assert payload["type"] == "error"
    assert payload["status"] == 401
    assert payload["error"] == "unauthenticated"
    assert payload["signin"] == "/signin"


def test_unauthenticated_envelope_without_signin_route_stays_plain():
    from fymo.auth.context import AuthRequired

    payload = _remote_error_payload(AuthRequired())
    assert "signin" not in payload


def test_unauthorized_bad_credentials_never_gets_signin():
    from fymo.remote.errors import Unauthorized

    set_signin_path("/signin")
    payload = _remote_error_payload(Unauthorized("invalid email or password"))
    assert payload["status"] == 401
    assert "signin" not in payload


def test_other_errors_never_get_signin():
    from fymo.remote.errors import Forbidden, NotFound

    set_signin_path("/signin")
    assert "signin" not in _remote_error_payload(Forbidden("no"))
    assert "signin" not in _remote_error_payload(NotFound("no"))


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def test_end_to_end_dispatch_attaches_signin(tmp_path, monkeypatch):
    """A remote function raising AuthRequired through the real dispatch path
    produces the envelope with the signin field."""
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    (tmp_path / "app" / "remote").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "remote" / "__init__.py").write_text("")
    (tmp_path / "app" / "remote" / "guarded.py").write_text(
        "from fymo.auth import AuthRequired\n"
        "def secret() -> str: raise AuthRequired()\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    from fymo.remote.discovery import file_hash
    h = file_hash(tmp_path / "app" / "remote" / "guarded.py")
    from fymo.remote import router as router_mod
    monkeypatch.setattr(
        router_mod, "_resolve_module_for_hash",
        lambda hash_: "guarded" if hash_ == h else None,
    )
    set_signin_path("/signin")

    raw = json.dumps({"payload": _b64url(devalue.stringify([]))}).encode()
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"/_fymo/remote/{h}/secret",
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": "",
        "HTTP_HOST": "x",
        "HTTP_ORIGIN": "http://x",
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }
    responses = []
    body = b"".join(handle_remote(environ, lambda s, hd: responses.append((s, hd))))
    envelope = json.loads(body)
    assert envelope["status"] == 401
    assert envelope["error"] == "unauthenticated"
    assert envelope["signin"] == "/signin"
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]
