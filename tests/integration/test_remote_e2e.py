"""End-to-end: an HTTP request to /__remote/<m>/<fn> through FymoApp."""
import io
import json
import sys
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_remote_call_through_fymoapp(example_app: Path, monkeypatch):
    # Add a remote module
    remote_dir = example_app / "app" / "remote"
    remote_dir.mkdir(parents=True, exist_ok=True)
    (remote_dir / "__init__.py").write_text("")
    (remote_dir / "greeter.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))
        body_payload = json.dumps({"args": ["alice"]}).encode()
        body = b"".join(app({
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/__remote/greeter/hello",
            "CONTENT_LENGTH": str(len(body_payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(body_payload),
            "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))

        assert responses[0][0].startswith("200")
        payload = json.loads(body)
        assert payload == {"ok": True, "data": "hi alice"}
    finally:
        if app.sidecar:
            app.sidecar.stop()
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
