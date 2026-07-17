"""Soft-nav data envelope carries the identity slot (issue #80 phase 4).

Same fake-app style as tests/core/test_soft_nav_redirect.py: minimal
router + manifest_cache, a controller module in sys.modules, the real
handle_data. The identity slot rides inside the devalue-encoded result,
the exact wire format the rest of the envelope uses.
"""
import io
import json
import sys
import types

import pytest

from fymo.auth import Identity, identify, public_identity
from fymo.auth.context import (
    register_identity_extras_hook,
    reset_identity_extras_hooks,
)
from fymo.auth.identity import reset_identity_resolvers
from fymo.auth.public import reset_public_identity
from fymo.build.manifest import RouteAssets
from fymo.core.soft_nav import handle_data
from fymo.remote import devalue
from fymo.remote.identity import set_secret


def _wsgi_get(app, path: str, headers=None):
    responses = []

    def sr(s, h):
        responses.append((s, h))

    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": "0", "CONTENT_TYPE": "", "HTTP_COOKIE": "",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    out = b"".join(handle_data(app, environ, sr))
    return responses[0], json.loads(out)


class _FakeRouter:
    def match(self, path):
        return {"controller": "identtest", "params": {}}

    def soft_nav_enabled(self, controller_name):
        return True


class _FakeManifest:
    def __init__(self):
        self.routes = {
            "identtest": RouteAssets(ssr="ssr/x.mjs", client="client/x.js", css=None, preload=[]),
        }
        self.layouts = {}
        self.global_css = []


class _FakeManifestCache:
    def get(self):
        return _FakeManifest()


class _FakeApp:
    def __init__(self):
        self.router = _FakeRouter()
        self.manifest_cache = _FakeManifestCache()
        self.dev = True

    class config_manager:
        @staticmethod
        def get_app_name():
            return "t"


@pytest.fixture(autouse=True)
def _clean():
    set_secret(b"test-secret-16-bytes-long")
    reset_identity_resolvers()
    reset_public_identity()
    reset_identity_extras_hooks()
    mod = types.ModuleType("app.controllers.identtest")
    mod.getContext = lambda: {"message": "hi"}
    sys.modules["app.controllers.identtest"] = mod
    yield
    reset_identity_resolvers()
    reset_public_identity()
    reset_identity_extras_hooks()
    sys.modules.pop("app.controllers.identtest", None)


def _register_header_resolver():
    @identify
    def by_header(event):
        uid = event.headers.get("x-user")
        return Identity(uid=uid) if uid else None


def test_result_envelope_carries_projected_identity():
    _register_header_resolver()

    @public_identity
    def project(ident):
        return {"uid": ident.uid, "name": "Alice"}

    (status, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever", headers={"x-user": "u1"})
    assert status.startswith("200")
    assert body["type"] == "result"
    data = devalue.parse(body["result"])
    assert data["identity"] == {"uid": "u1", "name": "Alice"}


def test_result_envelope_identity_null_when_anonymous():
    _register_header_resolver()
    (status, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever")
    data = devalue.parse(body["result"])
    assert data["identity"] is None


def test_result_envelope_identity_null_without_resolvers():
    (status, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever")
    data = devalue.parse(body["result"])
    assert data["identity"] is None


def test_extras_never_ride_the_envelope():
    _register_header_resolver()
    register_identity_extras_hook(lambda uid: {"role": "superadmin-extras-value"})

    @public_identity
    def project(ident):
        return {"uid": ident.uid}

    (_, _), body = _wsgi_get(_FakeApp(), "/_fymo/data/whatever", headers={"x-user": "u1"})
    assert "superadmin-extras-value" not in json.dumps(body)
    data = devalue.parse(body["result"])
    assert data["identity"] == {"uid": "u1"}
