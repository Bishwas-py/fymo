"""Full-page SSR identity slot (issue #80 phase 4).

Same direct-construction pattern as tests/core/test_template_renderer_layouts.py:
real ConfigManager/AssetManager/Router, FakeSidecar, controller module
registered in sys.modules. Proves the public_identity projection output
(and nothing else: no extras, no session token) reaches the rendered HTML
and the sidecar render payload.
"""
import sys
import types
from pathlib import Path

import pytest

from fymo.auth import Identity, identify, public_identity
from fymo.auth.context import (
    register_identity_extras_hook,
    reset_identity_extras_hooks,
)
from fymo.auth.identity import reset_identity_resolvers
from fymo.auth.public import reset_public_identity
from fymo.build.manifest import Manifest, RouteAssets
from fymo.core.assets import AssetManager
from fymo.core.config import ConfigManager
from fymo.core.router import Router
from fymo.core.template_renderer import TemplateRenderer
from fymo.remote.identity import set_secret

SESSION_TOKEN = "topsecret-session-token-value"


@pytest.fixture(autouse=True)
def _clean_registries():
    set_secret(b"test-secret-16-bytes-long")
    reset_identity_resolvers()
    reset_public_identity()
    reset_identity_extras_hooks()
    yield
    reset_identity_resolvers()
    reset_public_identity()
    reset_identity_extras_hooks()
    sys.modules.pop("app.controllers.home", None)


def _renderer(tmp_path: Path) -> TemplateRenderer:
    router = Router()
    router.routes = {"/": {"controller": "home", "action": "index", "template": "home/index.svelte"}}
    renderer = TemplateRenderer(
        tmp_path, ConfigManager(tmp_path, {"name": "Test App"}),
        AssetManager(tmp_path), router, dev=True,
    )
    renderer.auth_enabled = False

    class FakeManifestCache:
        def get(self):
            return Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])})
    renderer.manifest_cache = FakeManifestCache()

    captured = {}

    class FakeSidecar:
        def render(self, route_name, props, doc=None, identity=None):
            captured["identity"] = identity
            return {"body": "<div></div>", "head": ""}
    renderer.sidecar = FakeSidecar()
    renderer._captured = captured

    mod = types.ModuleType("app.controllers.home")
    mod.getContext = lambda: {"message": "hi"}
    mod.getDoc = lambda: {"title": "Home"}
    sys.modules["app.controllers.home"] = mod
    return renderer


def _environ(session=None):
    env = {
        "REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
        "REMOTE_ADDR": "127.0.0.1", "wsgi.url_scheme": "http",
    }
    if session is not None:
        env["HTTP_COOKIE"] = f"session={session}"
    return env


def _register_session_resolver():
    @identify
    def by_session(event):
        token = event.cookies.get("session")
        return Identity(uid="u_alice") if token == SESSION_TOKEN else None


def test_signed_in_render_embeds_projection_in_island_and_sidecar(tmp_path):
    _register_session_resolver()

    @public_identity
    def project(ident):
        return {"uid": ident.uid, "name": "Alice"}

    renderer = _renderer(tmp_path)
    html, status, _ = renderer.render_template("/", environ=_environ(session=SESSION_TOKEN))
    assert status == "200 OK"
    assert (
        '<script type="application/json" id="fymo-identity">'
        '{"uid": "u_alice", "name": "Alice"}</script>'
    ) in html
    assert renderer._captured["identity"] == {"uid": "u_alice", "name": "Alice"}


def test_anonymous_render_embeds_null_identity(tmp_path):
    _register_session_resolver()
    renderer = _renderer(tmp_path)
    html, status, _ = renderer.render_template("/", environ=_environ())
    assert status == "200 OK"
    assert '<script type="application/json" id="fymo-identity">null</script>' in html
    assert renderer._captured["identity"] is None


def test_no_resolvers_render_embeds_null_identity_without_environ_needed(tmp_path):
    renderer = _renderer(tmp_path)
    html, status, _ = renderer.render_template("/")
    assert status == "200 OK"
    assert '<script type="application/json" id="fymo-identity">null</script>' in html


def test_default_projection_is_uid_only(tmp_path):
    _register_session_resolver()
    renderer = _renderer(tmp_path)
    html, _, _ = renderer.render_template("/", environ=_environ(session=SESSION_TOKEN))
    assert '<script type="application/json" id="fymo-identity">{"uid": "u_alice"}</script>' in html


def test_extras_and_session_token_never_reach_the_html(tmp_path):
    """The security invariant: identity_extras never auto-serialize, and the
    raw session cookie value never appears anywhere in the payload. Only
    the projection's whitelisted fields cross."""
    _register_session_resolver()
    register_identity_extras_hook(
        lambda uid: {"email": "alice@corp.internal", "role": "superadmin-extras-value"}
    )

    @public_identity
    def project(ident):
        return {"uid": ident.uid}

    renderer = _renderer(tmp_path)
    html, status, _ = renderer.render_template("/", environ=_environ(session=SESSION_TOKEN))
    assert status == "200 OK"
    assert "alice@corp.internal" not in html
    assert "superadmin-extras-value" not in html
    assert SESSION_TOKEN not in html
    assert '"uid": "u_alice"' in html
