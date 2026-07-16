"""Redirect raised from a controller's getContext() on a direct page load
must produce a real HTTP 30x with a Location header -- not an HTML error
page. See fymo.remote.Redirect and issue #58.
"""
from pathlib import Path

from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.router import Router
from fymo.core.template_renderer import TemplateRenderer
from fymo.remote.errors import Redirect


def _make_renderer(tmp_path: Path, dev: bool = False) -> TemplateRenderer:
    config_manager = ConfigManager(tmp_path, {})
    asset_manager = AssetManager(tmp_path)
    router = Router()
    return TemplateRenderer(tmp_path, config_manager, asset_manager, router, dev=dev)


def test_redirect_produces_303_with_location_header(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise Redirect("/login")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, headers = r.render_template("/dashboard")
    assert status.startswith("303")
    assert dict(headers)["Location"] == "/login"


def test_redirect_honors_custom_status(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise Redirect("/login", status=307)

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    _, status, headers = r.render_template("/dashboard")
    assert status.startswith("307")
    assert dict(headers)["Location"] == "/login"


def test_non_redirect_paths_return_empty_headers(tmp_path, monkeypatch):
    """render_template's success path must still return the 3-tuple shape
    with an empty headers list, not break existing callers that only care
    about html/status."""
    r = _make_renderer(tmp_path, dev=True)

    def ok(route_path, environ=None):
        return "<html>hi</html>", "200 OK"

    monkeypatch.setattr(r, "_render_via_sidecar", ok)
    html, status, headers = r.render_template("/")
    assert html == "<html>hi</html>"
    assert status == "200 OK"
    assert headers == []
