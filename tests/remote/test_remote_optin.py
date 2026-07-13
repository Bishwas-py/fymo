"""`@remote` opt-in: bound the exposed surface of app/remote/*.py.

With `remote.explicit_optin` OFF (default, current behavior), every public
typed function in an app remote module is discovered and dispatchable —
proving back-compat for existing apps.

With `remote.explicit_optin` ON, only functions marked `@remote` are
discovered AND dispatchable; an unmarked public function is invisible to
both the build (discovery) and the router (dispatch time 404s it). Both
must agree, or a function could be listed in the client but 404, or be
callable despite not being in the manifest.
"""
import base64
import io
import json
import sys
from pathlib import Path

import pytest

from fymo.remote import devalue
from fymo.remote.decorators import remote as remote_decorator
from fymo.remote.discovery import discover_remote_modules, file_hash
import fymo.remote.router as router_mod
from fymo.remote.router import handle_remote


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


MODULE_SOURCE = (
    "from fymo.remote.decorators import remote\n"
    "@remote\n"
    "def marked(name: str) -> str: return f'hi {name}'\n"
    "def unmarked(name: str) -> str: return f'bye {name}'\n"
)


def _cleanup_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def test_decorator_marks_function_and_returns_it_unchanged():
    def fn(x: int) -> int:
        return x

    marked = remote_decorator(fn)

    assert marked is fn
    assert marked.__fymo_remote__ is True


# --- Discovery (build time) -------------------------------------------------

def test_discovery_hides_unmarked_functions_when_optin_enabled(tmp_path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": MODULE_SOURCE,
    })
    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project, remote_config={"explicit_optin": True})
    finally:
        sys.path.remove(str(project))
        _cleanup_app_modules()

    assert "marked" in result["posts"]
    assert "unmarked" not in result["posts"]


def test_discovery_exposes_all_functions_when_optin_disabled_default(tmp_path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": MODULE_SOURCE,
    })
    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project)  # no remote_config -> default off
    finally:
        sys.path.remove(str(project))
        _cleanup_app_modules()

    assert "marked" in result["posts"]
    assert "unmarked" in result["posts"]


# --- Router (dispatch time) --------------------------------------------------

def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_environ(path: str, args: list, *, host: str = "x", origin: str = "http://x") -> dict:
    body_obj = {"payload": _b64url(devalue.stringify(args))}
    raw = json.dumps(body_obj).encode()
    return {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": "",
        "HTTP_HOST": host,
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
        "HTTP_ORIGIN": origin,
    }


def _call(environ):
    responses = []

    def sr(status, headers):
        responses.append((status, headers))

    body = b"".join(handle_remote(environ, sr))
    return responses[0], json.loads(body)


@pytest.fixture
def optin_project(tmp_path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": MODULE_SOURCE,
    })
    monkeypatch.syspath_prepend(str(proj))
    h = file_hash(proj / "app/remote/posts.py")
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda hash_: "posts" if hash_ == h else None)
    yield proj, h
    _cleanup_app_modules()


def test_router_404s_unmarked_function_when_optin_enabled(optin_project, monkeypatch):
    proj, h = optin_project
    monkeypatch.setattr(router_mod, "_explicit_optin", True)

    env = _make_environ(f"/_fymo/remote/{h}/unmarked", ["alice"])
    (status, _), body = _call(env)

    assert status.startswith("200")
    assert body == {"type": "error", "status": 404, "error": "unknown_function"}


def test_router_dispatches_marked_function_when_optin_enabled(optin_project, monkeypatch):
    proj, h = optin_project
    monkeypatch.setattr(router_mod, "_explicit_optin", True)

    env = _make_environ(f"/_fymo/remote/{h}/marked", ["alice"])
    (status, _), body = _call(env)

    assert status.startswith("200")
    assert body["type"] == "result"
    assert devalue.parse(body["result"]) == "hi alice"


def test_router_dispatches_unmarked_function_when_optin_disabled_default(optin_project):
    proj, h = optin_project
    # _explicit_optin defaults to False; back-compat, no monkeypatch needed.

    env = _make_environ(f"/_fymo/remote/{h}/unmarked", ["alice"])
    (status, _), body = _call(env)

    assert status.startswith("200")
    assert body["type"] == "result"
    assert devalue.parse(body["result"]) == "bye alice"
