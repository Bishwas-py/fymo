"""Unknown routes must be a 404, not a 500 (issue #75).

The router's convention-based fallback matches almost any one- or
two-segment path, so a request like /favicon.ico used to sail past the
"no route" check, fail the manifest lookup, and surface as
500 "Route 'favicon' not in manifest. Run `fymo build`." -- a routing
miss dressed up as a server error, leaking a dev instruction to boot.

The distinction pinned here: a convention-based match with no manifest
entry is a route miss (404); an explicitly declared route missing from
the manifest is a genuine build error (500 stays).
"""
from pathlib import Path

from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.router import Router
from fymo.core.template_renderer import TemplateRenderer


class FakeManifest:
    def __init__(self, routes):
        self.routes = routes


class FakeManifestCache:
    def __init__(self, routes):
        self._manifest = FakeManifest(routes)

    def get(self):
        return self._manifest


def _make_renderer(tmp_path: Path, manifest_routes, router=None, dev=False):
    config_manager = ConfigManager(tmp_path, {})
    asset_manager = AssetManager(tmp_path)
    renderer = TemplateRenderer(
        tmp_path, config_manager, asset_manager, router or Router(), dev=dev
    )
    renderer.manifest_cache = FakeManifestCache(manifest_routes)
    return renderer


def test_convention_match_not_in_manifest_is_route_miss(tmp_path):
    r = _make_renderer(tmp_path, {"todos": object()})
    assert r.is_route_miss("/favicon.ico") is True
    assert r.is_route_miss("/no-such-page") is True


def test_convention_match_in_manifest_is_not_route_miss(tmp_path):
    """An SSR route that happens to collide with a well-known filename wins
    over the root-static allowlist: it's a real route, not a miss."""
    r = _make_renderer(tmp_path, {"favicon": object()})
    assert r.is_route_miss("/favicon.ico") is False


def test_declared_route_not_in_manifest_is_not_route_miss(tmp_path):
    """A route the app explicitly declared but never built is a build
    problem, not a routing one -- it must keep its 500."""
    router = Router()
    router.add_route("/posts", "posts", "index")
    r = _make_renderer(tmp_path, {}, router=router)
    assert r.is_route_miss("/posts") is False


def test_unmatched_path_is_route_miss(tmp_path):
    """Three or more segments never match convention routing."""
    r = _make_renderer(tmp_path, {"todos": object()})
    assert r.is_route_miss("/.well-known/acme-challenge/token") is True


def test_route_miss_renders_404_with_hint_in_dev(tmp_path):
    r = _make_renderer(tmp_path, {"todos": object()}, dev=True)
    html, status, _ = r.render_template("/no-such-page")
    assert status == "404 NOT FOUND"
    assert "No route matched" in html
    assert "/no-such-page" in html
    assert "routes" in html


def test_route_miss_renders_clean_404_in_prod(tmp_path):
    r = _make_renderer(tmp_path, {"todos": object()}, dev=False)
    html, status, _ = r.render_template("/no-such-page")
    assert status == "404 NOT FOUND"
    assert "404" in html
    # Zero internals: no dev instructions, no routing machinery names.
    for leak in ("fymo build", "manifest", "config/routes", "fymo.yml", "No route matched"):
        assert leak not in html


def test_404_page_escapes_the_requested_path(tmp_path):
    """The dev hint echoes the request path, which is user-controlled."""
    r = _make_renderer(tmp_path, {}, dev=True)
    html, status, _ = r.render_template("/<script>alert(1)</script>")
    assert status == "404 NOT FOUND"
    assert "<script>alert(1)</script>" not in html


def test_declared_route_missing_from_manifest_stays_500(tmp_path):
    router = Router()
    router.add_route("/posts", "posts", "index")
    r = _make_renderer(tmp_path, {}, router=router, dev=True)
    html, status, _ = r.render_template("/posts")
    assert status.startswith("500")
    assert "not in manifest" in html
