"""Unit coverage for the soft-nav data endpoint's Redirect handling.

Fast, no Node sidecar, no example app build -- a minimal fake `app` (router +
manifest_cache) plus a controller module registered directly in
sys.modules, mirroring the fake-controller style tests/core/test_ssr_controller.py
already uses for load_controller_context. Exercises the same
`{"type": "redirect", ...}` wire form the remote router already produces
(tests/remote/test_router.py) so a controller's getContext() raising Redirect
during a soft-nav transition behaves identically to a remote-function call
raising it.
"""
import io
import json
import sys
import types

import pytest

from fymo.build.manifest import RouteAssets
from fymo.core.soft_nav import handle_data
from fymo.remote.errors import Redirect, NotFound


def _wsgi_get(app, path: str):
    responses = []
    def sr(s, h): responses.append((s, h))
    out = b"".join(handle_data(app, {
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": "0", "CONTENT_TYPE": "",
        "HTTP_COOKIE": "",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], json.loads(out)


class _FakeRouter:
    def match(self, path):
        return {"controller": "redirtest", "params": {}}

    def soft_nav_enabled(self, controller_name):
        return True


class _FakeManifest:
    def __init__(self):
        self.routes = {
            "redirtest": RouteAssets(ssr="ssr/x.mjs", client="client/x.js", css=None, preload=[]),
        }
        self.layouts = {}


class _FakeManifestCache:
    def get(self):
        return _FakeManifest()


class _FakeApp:
    def __init__(self):
        self.router = _FakeRouter()
        self.manifest_cache = _FakeManifestCache()
        self.dev = True
        self.auth_enabled = False


def _register_controller(getContext):
    mod = types.ModuleType("app.controllers.redirtest")
    mod.getContext = getContext
    sys.modules["app.controllers.redirtest"] = mod
    return mod


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    sys.modules.pop("app.controllers.redirtest", None)


def test_getcontext_redirect_returns_redirect_envelope():
    _register_controller(lambda: (_ for _ in ()).throw(Redirect("/login")))
    (status, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever")
    assert status.startswith("200")
    assert body == {"type": "redirect", "location": "/login", "status": 303}


def test_getcontext_redirect_honors_custom_status():
    _register_controller(lambda: (_ for _ in ()).throw(Redirect("/login", status=307)))
    (status, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever")
    assert status.startswith("200")
    assert body == {"type": "redirect", "location": "/login", "status": 307}


def test_getcontext_remote_error_maps_status_instead_of_flattening_to_500():
    """A NotFound/etc RemoteError raised from getContext() during soft-nav
    must map to its real status/code, matching what template_renderer.py
    already does for the full-page SSR path -- previously any RemoteError
    here fell through to the generic `controller_failed` 500, losing the
    status/code entirely."""
    _register_controller(lambda: (_ for _ in ()).throw(NotFound("nope")))
    (status, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever")
    assert status.startswith("200")
    assert body == {"type": "error", "status": 404, "error": "not_found", "message": "nope"}
