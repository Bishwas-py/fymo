"""End-to-end: a controller's getContext() raising Redirect on a direct
(full) page load must produce a real HTTP 30x with a Location header, not
an HTML page -- see fymo.remote.Redirect and issue #58."""
import io
import sys
from pathlib import Path

import pytest


def _wsgi_get_raw(app, path: str):
    responses = []
    def sr(s, h): responses.append((s, h))
    body = b"".join(app({
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": "0", "CONTENT_TYPE": "",
        "HTTP_COOKIE": "",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], body


@pytest.mark.usefixtures("node_available")
def test_getcontext_redirect_produces_303_with_location(blog_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from fymo import create_app
    app = create_app(blog_app)

    import app.controllers.home as home_controller
    from fymo.remote import Redirect

    def raise_redirect():
        raise Redirect("/login")

    monkeypatch.setattr(home_controller, "getContext", raise_redirect)

    try:
        (status, headers), body = _wsgi_get_raw(app, "/")
        assert status.startswith("303")
        header_dict = dict(headers)
        assert header_dict["Location"] == "/login"
        assert body == b""
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_getcontext_redirect_honors_custom_status(blog_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from fymo import create_app
    app = create_app(blog_app)

    import app.controllers.home as home_controller
    from fymo.remote import Redirect

    def raise_redirect():
        raise Redirect("/dashboard", status=307)

    monkeypatch.setattr(home_controller, "getContext", raise_redirect)

    try:
        (status, headers), body = _wsgi_get_raw(app, "/")
        assert status.startswith("307")
        assert dict(headers)["Location"] == "/dashboard"
    finally:
        if app.sidecar:
            app.sidecar.stop()
