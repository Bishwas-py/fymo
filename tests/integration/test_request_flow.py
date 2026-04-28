import io
import os
import re
import sys
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_request_renders_via_sidecar_when_flag_set(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")
    monkeypatch.chdir(example_app)

    from fymo import create_app
    app = create_app(example_app)

    responses = []
    def start_response(status, headers):
        responses.append((status, headers))

    body = b"".join(app({
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": __import__("io").BytesIO(),
        "wsgi.errors": __import__("sys").stderr,
        "wsgi.url_scheme": "http",
    }, start_response))

    assert responses[0][0].startswith("200")
    text = body.decode("utf-8")
    assert "todo-app" in text
    assert "<div id=\"svelte-app\">" in text

    if hasattr(app, 'sidecar') and app.sidecar:
        app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_response_html_under_10kb(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")

    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": __import__("io").BytesIO(),
            "wsgi.errors": __import__("sys").stderr,
            "wsgi.url_scheme": "http",
        }, start_response))

        assert responses[0][0].startswith("200")
        assert len(body) < 10_000, f"response size {len(body)}B exceeds 10KB limit"
        # Must reference the bundle externally, not inline
        assert b'<script type="module" src="/dist/client/todos.' in body
        assert b'_fymo_packages' not in body  # old IIFE bundle inlining must be gone
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_response_includes_stylesheet_link_and_css_serves(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        # Get the page
        responses = []
        def sr(s, h):
            responses.append((s, h))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr))
        assert responses[0][0].startswith("200")

        # Page must reference a stylesheet
        assert b'rel="stylesheet"' in body, "no <link rel=stylesheet> in HTML"
        m = re.search(rb'href="(/dist/client/[^"]+\.css)"', body)
        assert m is not None, "no CSS href found"
        css_url = m.group(1).decode()

        # And that stylesheet must serve via /dist
        responses2 = []
        def sr2(s, h):
            responses2.append((s, h))
        css_body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": css_url, "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr2))
        assert responses2[0][0].startswith("200"), f"CSS request failed: {responses2[0][0]}"
        assert b"todo-app" in css_body or len(css_body) > 0
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_response_includes_doc_island_and_client_assigns_getDoc(example_app, monkeypatch):
    """Hydration regression: getDoc() must be defined client-side.

    Without this the example app's `<p>Document Title: {docData.title}</p>`
    throws `ReferenceError: getDoc is not defined` during hydrate().
    """
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        import io, sys
        responses = []
        def sr(s, h):
            responses.append((s, h))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr))

        # HTML must include the doc JSON island
        assert b'id="svelte-doc"' in body, "no <script id=svelte-doc> in HTML"

        # Client entry bundle must read it and assign globalThis.getDoc
        import re
        m = re.search(rb'src="(/dist/client/[^"]+\.js)"', body)
        assert m is not None
        bundle_url = m.group(1).decode()

        responses2 = []
        def sr2(s, h):
            responses2.append((s, h))
        bundle_body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": bundle_url, "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr2))
        assert responses2[0][0].startswith("200")
        assert b"svelte-doc" in bundle_body, "client bundle does not read svelte-doc island"
        assert b"getDoc" in bundle_body, "client bundle does not assign globalThis.getDoc"
    finally:
        if app.sidecar:
            app.sidecar.stop()
