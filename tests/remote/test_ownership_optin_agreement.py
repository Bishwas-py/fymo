"""Agreement test pinning that discovery (build-time codegen) and the router
(runtime dispatch) apply the exact same "may this attribute be called
remotely" rule: owned by the module (defined there, not merely imported
into it), and — when explicit opt-in is on — carrying `__fymo_remote__`.

Historically this rule was implemented independently in
`discovery._collect_module_functions` and `router._resolve_fn_in_module`.
This test scaffolds a module with an imported function, an owned-but-unmarked
function, and an owned-and-marked function, then asserts discovery's
manifest and the router's dispatch decision agree in both explicit_optin
states. It must pass before AND after the two checks are unified behind a
shared helper (`discovery.is_exposed_remote_fn`).
"""
import base64
import io
import json
import sys
from pathlib import Path

import pytest

from fymo.remote import devalue
from fymo.remote.discovery import discover_remote_modules, file_hash
import fymo.remote.router as router_mod
from fymo.remote.router import handle_remote

MODULE_SOURCE = (
    "from os.path import isfile as imported_check\n"
    "from fymo.remote.decorators import remote\n"
    "@remote\n"
    "def marked(name: str) -> str: return f'hi {name}'\n"
    "def unmarked(name: str) -> str: return f'bye {name}'\n"
    "class Widget:\n"
    "    def __call__(self, name: str) -> str: return f'called {name}'\n"
    "widget = Widget()\n"
)


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _cleanup_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


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
def agreement_project(tmp_path, monkeypatch):
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


def _dispatch(h, fn_name, args=("alice",)):
    env = _make_environ(f"/_fymo/remote/{h}/{fn_name}", list(args))
    (status, _), body = _call(env)
    assert status.startswith("200")
    return body


@pytest.mark.parametrize("explicit_optin", [False, True])
def test_discovery_and_router_agree_on_imported_function_rejection(agreement_project, monkeypatch, explicit_optin):
    proj, h = agreement_project
    monkeypatch.setattr(router_mod, "_explicit_optin", explicit_optin)

    manifest = discover_remote_modules(proj, remote_config={"explicit_optin": explicit_optin})
    assert "imported_check" not in manifest["posts"]

    body = _dispatch(h, "imported_check")
    assert body == {"type": "error", "status": 404, "error": "unknown_function"}


def test_discovery_and_router_agree_on_owned_unmarked_rejected_under_explicit_optin(agreement_project, monkeypatch):
    proj, h = agreement_project
    monkeypatch.setattr(router_mod, "_explicit_optin", True)

    manifest = discover_remote_modules(proj, remote_config={"explicit_optin": True})
    assert "unmarked" not in manifest["posts"]

    body = _dispatch(h, "unmarked")
    assert body == {"type": "error", "status": 404, "error": "unknown_function"}


def test_discovery_and_router_agree_on_owned_marked_accepted_under_explicit_optin(agreement_project, monkeypatch):
    proj, h = agreement_project
    monkeypatch.setattr(router_mod, "_explicit_optin", True)

    manifest = discover_remote_modules(proj, remote_config={"explicit_optin": True})
    assert "marked" in manifest["posts"]

    body = _dispatch(h, "marked")
    assert body["type"] == "result"
    assert devalue.parse(body["result"]) == "hi alice"


def test_discovery_and_router_agree_on_plain_acceptance_when_optin_disabled(agreement_project, monkeypatch):
    proj, h = agreement_project
    monkeypatch.setattr(router_mod, "_explicit_optin", False)

    manifest = discover_remote_modules(proj)  # no remote_config -> default off
    assert "unmarked" in manifest["posts"]
    assert "marked" in manifest["posts"]

    body_unmarked = _dispatch(h, "unmarked")
    assert body_unmarked["type"] == "result"
    assert devalue.parse(body_unmarked["result"]) == "bye alice"

    body_marked = _dispatch(h, "marked")
    assert body_marked["type"] == "result"
    assert devalue.parse(body_marked["result"]) == "hi alice"


def test_non_function_module_attributes_are_not_dispatchable(agreement_project, monkeypatch):
    """Pins the security property that non-function module attributes are not
    dispatchable even though the module hash is public and per-module.

    The module hash appears in the generated client, so anyone can hand-craft
    a POST to /_fymo/remote/<hash>/<name> for ANY attribute name. The router
    once gated dispatch on `callable(fn)`, which would have accepted a class
    defined in the module (instantiating it on demand) or a callable instance
    assigned at module level — things discovery never advertises. The shared
    `is_exposed_remote_fn` check requires `inspect.isfunction`; this test
    guards against a future "simplification" back toward `callable` silently
    reopening that gap. Runs under explicit_optin=False, the permissive
    default, which is where the old hole lived.
    """
    proj, h = agreement_project
    monkeypatch.setattr(router_mod, "_explicit_optin", False)

    manifest = discover_remote_modules(proj)
    assert "Widget" not in manifest["posts"]
    assert "widget" not in manifest["posts"]

    # A class defined in the module: callable, owned, but not a function.
    body_class = _dispatch(h, "Widget")
    assert body_class == {"type": "error", "status": 404, "error": "unknown_function"}

    # A callable instance assigned at module level.
    body_instance = _dispatch(h, "widget")
    assert body_instance == {"type": "error", "status": 404, "error": "unknown_function"}
