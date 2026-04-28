import os
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
