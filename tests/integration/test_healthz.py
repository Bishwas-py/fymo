"""GET /healthz: 200 when the Node sidecar is alive, 503 when it's down."""
import io
import json
import sys
from pathlib import Path
import pytest


def _wsgi_get(app, path: str, remote_addr: str = "127.0.0.1"):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    body = b"".join(app({
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": remote_addr,
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], body


@pytest.mark.usefixtures("node_available")
def test_healthz_ok(example_app: Path):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        (status, headers), body = _wsgi_get(app, "/healthz")
        assert status.startswith("200")
        assert json.loads(body)["status"] == "ok"
        header_map = {k.lower(): v for k, v in headers}
        assert header_map.get("cache-control") == "no-cache"
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_healthz_degraded_when_sidecar_down(example_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        def _boom():
            raise RuntimeError("sidecar unreachable")
        monkeypatch.setattr(app.sidecar, "ping", _boom)

        (status, _), body = _wsgi_get(app, "/healthz")
        assert status.startswith("503")
        assert json.loads(body)["status"] == "degraded"
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_healthz_exempt_from_rate_limit(example_app: Path):
    """A load balancer / k8s probe polling /healthz faster than the default
    60 rpm rate limit must never see a 429 — a healthy instance would
    otherwise get marked down."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        for i in range(65):
            (status, _), body = _wsgi_get(app, "/healthz", remote_addr="10.0.0.7")
            assert status.startswith("200"), f"request {i} got {status!r}, expected 200"
            assert json.loads(body)["status"] == "ok"
    finally:
        app.shutdown()
