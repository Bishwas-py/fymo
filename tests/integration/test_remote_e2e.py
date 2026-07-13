"""End-to-end: an HTTP request to /_fymo/remote/<hash>/<fn> through FymoApp."""
import base64
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
    from fymo.remote import devalue
    BuildPipeline(project_root=example_app).build(dev=False)

    # The build emits a content-hash for the greeter module; pull it from manifest.
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["greeter"]["hash"]

    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))

        # New wire: payload is base64url(devalue.stringify(args)).
        payload_b64 = base64.urlsafe_b64encode(
            devalue.stringify(["alice"]).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        body_payload = json.dumps({"payload": payload_b64}).encode()

        body = b"".join(app({
            "REQUEST_METHOD": "POST",
            "PATH_INFO": f"/_fymo/remote/{hash_}/hello",
            "CONTENT_LENGTH": str(len(body_payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "HTTP_HOST": "x",
            "HTTP_ORIGIN": "http://x",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(body_payload),
            "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))

        # New envelope: ALWAYS HTTP 200; type/result drives semantics.
        assert responses[0][0].startswith("200")
        env = json.loads(body)
        assert env["type"] == "result"
        assert devalue.parse(env["result"]) == "hi alice"
    finally:
        if app.sidecar:
            app.sidecar.stop()
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
