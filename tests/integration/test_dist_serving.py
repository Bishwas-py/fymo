import io
import sys
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_dist_assets_served_with_immutable_caching(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")

    from fymo import create_app
    app = create_app(example_app)
    try:
        client_dir = example_app / "dist" / "client"
        bundle = next(client_dir.glob("todos.*.js"))
        rel = bundle.relative_to(example_app / "dist").as_posix()

        responses = []
        def start_response(status, headers):
            responses.append((status, headers))

        body = b"".join(app({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": f"/dist/{rel}",
            "QUERY_STRING": "",
            "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))

        assert responses[0][0].startswith("200")
        headers = dict(responses[0][1])
        assert "Cache-Control" in headers
        assert "immutable" in headers["Cache-Control"]
        assert headers.get("Content-Type", "").startswith("application/javascript")
        # With code splitting on, hydrate may live in a shared chunk imported by
        # this entry. Either inline OR a side-effect import to a chunk-*.js is OK.
        assert b"hydrate" in body or b"chunk-" in body
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_dist_path_traversal_rejected(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")

    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))
        body = b"".join(app({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/dist/../../etc/passwd",
            "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))
        assert responses[0][0].startswith("404") or responses[0][0].startswith("403")
    finally:
        if app.sidecar:
            app.sidecar.stop()
