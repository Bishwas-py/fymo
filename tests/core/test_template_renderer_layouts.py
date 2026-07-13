"""Unit coverage for TemplateRenderer's leaf+layout props assembly.

Follows the same direct-construction pattern as tests/core/test_error_page_xss.py
(the only other file that instantiates TemplateRenderer directly) -- real
ConfigManager/AssetManager/Router, no mocks, since none of the three do
anything expensive or I/O-bound in their constructors."""
from pathlib import Path

from fymo.build.manifest import Manifest, RouteAssets, LayoutRefAsset
from fymo.core.router import Router
from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.template_renderer import TemplateRenderer


def _renderer(tmp_path: Path) -> TemplateRenderer:
    router = Router()
    router.routes = {"/": {"controller": "home", "action": "index", "template": "home/index.svelte"}}
    config_manager = ConfigManager(tmp_path, {"name": "Test App"})
    asset_manager = AssetManager(tmp_path)
    renderer = TemplateRenderer(tmp_path, config_manager, asset_manager, router, dev=True)
    renderer.auth_enabled = False
    return renderer


def test_props_are_flat_when_route_has_no_layout_chain(tmp_path, monkeypatch):
    renderer = _renderer(tmp_path)

    class FakeManifestCache:
        def get(self):
            from fymo.build.manifest import Manifest, RouteAssets
            return Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])})
    renderer.manifest_cache = FakeManifestCache()

    captured = {}
    class FakeSidecar:
        def render(self, route_name, props, doc=None):
            captured["props"] = props
            return {"body": "<div></div>", "head": ""}
    renderer.sidecar = FakeSidecar()

    import sys, types
    mod = types.ModuleType("app.controllers.home")
    mod.getContext = lambda: {"message": "hi"}
    mod.getDoc = lambda: {"title": "Home"}
    sys.modules["app.controllers.home"] = mod
    try:
        html, status = renderer.render_template("/")
    finally:
        del sys.modules["app.controllers.home"]

    assert status == "200 OK"
    assert captured["props"] == {"message": "hi"}  # flat, not nested under leafProps


def test_props_are_nested_when_route_has_layout_chain(tmp_path, monkeypatch):
    renderer = _renderer(tmp_path)

    class FakeManifestCache:
        def get(self):
            return Manifest(routes={
                "home": RouteAssets(
                    ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[],
                    layout_chain=[LayoutRefAsset(level="root", id="_root", controller_module=None)],
                    uses_layout_shell=True,
                )
            })
    renderer.manifest_cache = FakeManifestCache()

    captured = {}
    class FakeSidecar:
        def render(self, route_name, props, doc=None):
            captured["props"] = props
            return {"body": "<div></div>", "head": ""}
    renderer.sidecar = FakeSidecar()

    import sys, types
    mod = types.ModuleType("app.controllers.home")
    mod.getContext = lambda: {"message": "hi"}
    mod.getDoc = lambda: {"title": "Home"}
    sys.modules["app.controllers.home"] = mod
    try:
        html, status = renderer.render_template("/")
    finally:
        del sys.modules["app.controllers.home"]

    assert status == "200 OK"
    assert captured["props"] == {
        "leafProps": {"message": "hi"},
        "layoutProps": {"root": {}, "resource": {}},
    }
