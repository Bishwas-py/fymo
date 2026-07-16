"""Regression tests for reflected-XSS in SSR error pages.

Exception messages often echo user-controlled route params (e.g. a failed
`int(param)` conversion embeds the raw param in the message). Rendering that
message unescaped into an HTML error page is a reflected-XSS vector. These
tests pin the fix: dev mode shows the escaped exception text, prod mode
shows a generic body with no exception text at all.
"""
from pathlib import Path

from fymo.build.manifest import RouteAssets
from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.exceptions import ConfigurationError
from fymo.core.router import Router
from fymo.core.template_renderer import TemplateRenderer


def _make_renderer(tmp_path: Path, dev: bool = False) -> TemplateRenderer:
    config_manager = ConfigManager(tmp_path, {})
    asset_manager = AssetManager(tmp_path)
    router = Router()
    return TemplateRenderer(tmp_path, config_manager, asset_manager, router, dev=dev)


def test_render_error_escapes_exception_text_in_dev(tmp_path):
    r = _make_renderer(tmp_path, dev=True)
    html, status = r._render_error(ValueError("<script>alert(1)</script>"), "Server Error")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_error_omits_exception_text_in_prod(tmp_path):
    r = _make_renderer(tmp_path, dev=False)
    html, status = r._render_error(ValueError("<script>alert(1)</script>"), "Server Error")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "alert(1)" not in html
    assert "&lt;script&gt;" not in html


def test_render_template_generic_error_escapes_in_dev(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise ValueError("<script>alert(1)</script>")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/whatever")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_template_generic_error_omits_text_in_prod(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=False)

    def boom(route_path, environ=None):
        raise ValueError("<script>alert(1)</script>")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/whatever")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "alert(1)" not in html


def test_render_template_message_style_error_escapes_in_dev(tmp_path, monkeypatch):
    """FymoError subclasses carry `.message` instead
    of a plain str(); confirm that code path also routes through the
    escaping helper rather than interpolating `.message` raw into HTML."""
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise ConfigurationError("<script>alert(1)</script>")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/whatever")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_template_message_style_error_omits_text_in_prod(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=False)

    def boom(route_path, environ=None):
        raise ConfigurationError("<script>alert(1)</script>")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/whatever")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "alert(1)" not in html
    assert "&lt;script&gt;" not in html


class _FakeManifest:
    def __init__(self, route_name):
        # A real RouteAssets (rather than a bare object()) so that
        # `_render_via_sidecar`'s `assets.layout_chain` check -- added once
        # layout-chain support landed -- has a real (empty) list to read,
        # matching every route this test's FakeSidecar short-circuits before
        # `.css`/`.client`/`.preload` would ever be touched.
        self.routes = {route_name: RouteAssets(ssr="ssr/x.mjs", client="client/x.js", css=None, preload=[])}


class _FakeManifestCache:
    def __init__(self, route_name):
        self._manifest = _FakeManifest(route_name)

    def get(self):
        return self._manifest


class _FakeSidecar:
    def render(self, route_name, props, doc=None):
        from fymo.core.sidecar import SidecarError
        raise SidecarError("<script>alert(1)</script>")


def _wire_sidecar_error(r, monkeypatch, route_name="home"):
    monkeypatch.setattr(
        r.router, "match", lambda path: {"controller": f"{route_name}.controller", "params": {}}
    )
    monkeypatch.setattr(
        r, "_load_controller_data",
        lambda controller_module, params=None, environ=None: (None, {}, {})
    )
    r.manifest_cache = _FakeManifestCache(route_name)
    r.sidecar = _FakeSidecar()


def test_ssr_error_escapes_exception_text_in_dev(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)
    _wire_sidecar_error(r, monkeypatch)
    html, status = r._render_via_sidecar("/home")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_ssr_error_omits_exception_text_in_prod(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=False)
    _wire_sidecar_error(r, monkeypatch)
    html, status = r._render_via_sidecar("/home")
    assert status == "500 INTERNAL SERVER ERROR"
    assert "<script>" not in html
    assert "alert(1)" not in html
