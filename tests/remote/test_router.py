"""WSGI handler for remote function calls — SvelteKit-style wire."""
import base64
import io
import json
import sys
from pathlib import Path
import pytest
from fymo.remote.router import handle_remote
from fymo.remote import devalue


def _scaffold(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_environ(path: str, args: list, *, cookies: str = "", origin: str | None = "http://x", host: str = "x", scheme: str = "http"):
    body_obj = {"payload": _b64url(devalue.stringify(args))}
    raw = json.dumps(body_obj).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "HTTP_HOST": host,
        "wsgi.url_scheme": scheme,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    return env


def _call(environ):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    body = b"".join(handle_remote(environ, sr))
    return responses[0], json.loads(body)


@pytest.fixture
def remote_project(tmp_path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": (
            "from fymo.remote import current_uid, NotFound\n"
            "def hello(name: str) -> str: return f'hi {name}'\n"
            "def whoami() -> str: return current_uid()\n"
            "def boom() -> str: raise NotFound('nope')\n"
        ),
    })
    monkeypatch.syspath_prepend(str(proj))

    # Stub the manifest hash lookup
    from fymo.remote.discovery import file_hash
    h = file_hash(proj / "app/remote/posts.py")
    from fymo.remote import router as router_mod
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda hash_: "posts" if hash_ == h else None)

    yield proj, h
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]


def test_calls_function_returns_result_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", ["alice"], host="x", origin="http://x")
    (status, headers), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "result"
    assert devalue.parse(body["result"]) == "hi alice"


def test_cross_origin_returns_403_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", ["alice"], host="yoursite.com", origin="https://evil.com")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body == {"type": "error", "status": 403, "error": "cross_origin"}


def test_missing_origin_is_allowed(remote_project):
    """Server-to-server / curl with no Origin header should not be CSRF-blocked."""
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", ["alice"], host="x", origin=None)
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "result"


def test_unknown_hash_returns_404_envelope(remote_project):
    env = _make_environ("/_fymo/remote/000000000000/hello", ["alice"], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body == {"type": "error", "status": 404, "error": "unknown_module"}


def test_unknown_function_returns_404_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/nope", [], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 404


def test_validation_error_returns_422_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", [123], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 422


def test_domain_error_returns_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/boom", [], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 404
    assert body["error"] == "not_found"


def test_uid_cookie_issued_on_first_call(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/whoami", [], host="x", origin="http://x")
    (status, headers), body = _call(env)
    set_cookie = next((v for k, v in headers if k.lower() == "set-cookie"), None)
    assert set_cookie is not None
    assert "fymo_uid=" in set_cookie


def test_uid_cookie_secure_flag_only_on_https(remote_project):
    """Secure flag must be present over https and absent over http."""
    proj, h = remote_project
    # http: no Secure
    env = _make_environ(f"/_fymo/remote/{h}/whoami", [], scheme="http", origin="http://x")
    (_, headers), _ = _call(env)
    cookie = next(v for k, v in headers if k.lower() == "set-cookie")
    assert "Secure" not in cookie
    # https: Secure present
    env = _make_environ(f"/_fymo/remote/{h}/whoami", [], scheme="https", origin="https://x")
    (_, headers), _ = _call(env)
    cookie = next(v for k, v in headers if k.lower() == "set-cookie")
    assert "Secure" in cookie


def test_500_omits_traceback_when_dev_mode_off(remote_project, monkeypatch):
    """In production (default), internal-error responses must not leak traceback or message."""
    proj, h = remote_project
    from fymo.remote import router as router_mod
    monkeypatch.setattr(router_mod, "_dev_mode", False)
    # Wire a function that raises a non-RemoteError exception
    (proj / "app/remote/posts.py").write_text(
        "def explode() -> str: raise RuntimeError('secret internal detail')\n"
    )
    # Recompute hash since we rewrote the file
    from fymo.remote.discovery import file_hash
    new_h = file_hash(proj / "app/remote/posts.py")
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda hash_: "posts" if hash_ == new_h else None)
    # Force module reimport
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    env = _make_environ(f"/_fymo/remote/{new_h}/explode", [], host="x", origin="http://x")
    (_, _), body = _call(env)
    assert body == {"type": "error", "status": 500, "error": "internal"}
    # No traceback, no message — opaque
    assert "traceback" not in body
    assert "message" not in body


def test_500_includes_traceback_when_dev_mode_on(remote_project, monkeypatch):
    proj, h = remote_project
    from fymo.remote import router as router_mod
    monkeypatch.setattr(router_mod, "_dev_mode", True)
    (proj / "app/remote/posts.py").write_text(
        "def explode() -> str: raise RuntimeError('explosion details')\n"
    )
    from fymo.remote.discovery import file_hash
    new_h = file_hash(proj / "app/remote/posts.py")
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda hash_: "posts" if hash_ == new_h else None)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    env = _make_environ(f"/_fymo/remote/{new_h}/explode", [], host="x", origin="http://x")
    (_, _), body = _call(env)
    assert body["type"] == "error"
    assert body["status"] == 500
    assert "explosion details" in body.get("message", "")
    assert "Traceback" in body.get("traceback", "")
