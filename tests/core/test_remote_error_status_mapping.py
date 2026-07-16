"""RemoteError raised directly inside a page controller's getContext() (not
via a remote-function RPC call) must map to its real status/code instead of
always flattening to a generic 500 -- e.g. `raise NotFound(...)` for a
missing post slug should render a 404, not "Server Error"."""
from pathlib import Path

from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.router import Router
from fymo.core.template_renderer import TemplateRenderer
from fymo.remote.errors import NotFound, Unauthorized, Forbidden, Conflict


def _make_renderer(tmp_path: Path, dev: bool = False) -> TemplateRenderer:
    config_manager = ConfigManager(tmp_path, {})
    asset_manager = AssetManager(tmp_path)
    router = Router()
    return TemplateRenderer(tmp_path, config_manager, asset_manager, router, dev=dev)


def test_not_found_renders_404_not_500(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise NotFound("post 'missing-slug' not found")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/posts/missing-slug")
    assert status == "404 NOT FOUND"
    assert "Not Found" in html


def test_unauthorized_renders_401(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise Unauthorized("sign in required")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    _, status, _headers = r.render_template("/whatever")
    assert status == "401 UNAUTHORIZED"


def test_forbidden_renders_403(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise Forbidden("not your post")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    _, status, _headers = r.render_template("/whatever")
    assert status == "403 FORBIDDEN"


def test_conflict_renders_409(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise Conflict("already exists")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    _, status, _headers = r.render_template("/whatever")
    assert status == "409 CONFLICT"


def test_not_found_message_still_escaped_in_dev(tmp_path, monkeypatch):
    """RemoteError messages are still user-controlled-adjacent (echo a route
    param, e.g. the slug) -- must go through the same escaping path as every
    other exception type, not a new unescaped shortcut."""
    r = _make_renderer(tmp_path, dev=True)

    def boom(route_path, environ=None):
        raise NotFound("post '<script>alert(1)</script>' not found")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/whatever")
    assert status == "404 NOT FOUND"
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_not_found_omits_message_in_prod(tmp_path, monkeypatch):
    r = _make_renderer(tmp_path, dev=False)

    def boom(route_path, environ=None):
        raise NotFound("post 'secret-internal-id-42' not found")

    monkeypatch.setattr(r, "_render_via_sidecar", boom)
    html, status, _headers = r.render_template("/whatever")
    assert status == "404 NOT FOUND"
    assert "secret-internal-id-42" not in html
