"""FymoApp.__call__ emits one structured access-log line per request.

/healthz is exempt (see tests/integration/test_healthz.py for its own
behavior) — health-check polling is far too frequent to be worth logging.
"""
import io
import json
import sys
from pathlib import Path
import pytest


def _wsgi_get(app, path: str):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    body = b"".join(app({
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], body


@pytest.mark.usefixtures("node_available")
def test_access_log_emits_json_line_in_prod(example_app: Path, caplog):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app, dev=False)  # prod => JSON access log
    try:
        with caplog.at_level("INFO", logger="fymo"):
            (status, _), _ = _wsgi_get(app, "/")
        assert status.startswith("200")
        rec = json.loads(caplog.records[-1].getMessage())
        assert rec["method"] == "GET"
        assert rec["path"] == "/"
        assert rec["status"] == 200
        assert isinstance(rec["duration_ms"], (int, float))
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_healthz_is_not_access_logged(example_app: Path, caplog):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app, dev=False)
    try:
        with caplog.at_level("INFO", logger="fymo"):
            (status, _), _ = _wsgi_get(app, "/healthz")
        assert status.startswith("200")
        assert len(caplog.records) == 0
    finally:
        app.shutdown()
