"""Frontend identity boundary end to end (issue #80 phase 4).

Builds a real app (todo_app copy) whose template imports the $fymo/auth
store, with an @identify resolver and a @public_identity projection, and
proves the whole boundary through the real pipeline: esbuild resolves the
$fymo alias, the sidecar renders $identity server-side, the fymo-identity
island crosses in the HTML, the soft-nav envelope carries the slot, a 401
unauthenticated remote envelope points at the signin route, and the built
client bundle actually hydrates (jsdom, real hydrate()).
"""
import base64
import io
import json
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from fymo.build.pipeline import BuildPipeline
from fymo.remote import devalue

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TODO_APP = REPO_ROOT / "examples" / "todo_app"
HYDRATION_CHECK_JS = REPO_ROOT / "fymo" / "build" / "js" / "hydration_check.mjs"

FYMO_YML = """\
name: todo_app
version: 1.0.0
routes:
  root: home.index
  resources:
    - todos
    - home
  signin: home.index
build:
  output_dir: dist
"""

RESOLVER = """\
from fymo.auth import identify, Identity

@identify
def by_header(event):
    uid = event.headers.get("x-user")
    return Identity(uid=uid) if uid else None
"""

PUBLIC = """\
from fymo.auth import public_identity

@public_identity
def project(ident):
    return {"uid": ident.uid, "name": "user-" + ident.uid}
"""

TEMPLATE = """\
<script>
  import { identity } from '$fymo/auth';
  let { title, message } = $props();
</script>

<div class="container">
  <h1>{title}</h1>
  <p>{message}</p>
  {#if $identity}
    <p id="who">Hi {$identity.name}</p>
  {:else}
    <p id="who"><a href="/signin">Sign in</a></p>
  {/if}
</div>
"""

GUARDED_REMOTE = """\
from fymo.auth import AuthRequired, current_uid
from fymo.remote import remote


@remote
def secret_note() -> str:
    if current_uid() is None:
        raise AuthRequired()
    return "the note"
"""


@pytest.fixture(scope="module")
def built_app(tmp_path_factory, node_available):
    dest = tmp_path_factory.mktemp("identity_boundary") / "todo_app"
    shutil.copytree(
        TODO_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo")
    )
    nm = TODO_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/todo_app/node_modules not found; run npm install in examples/todo_app/")
    (dest / "fymo.yml").write_text(FYMO_YML)
    auth_dir = dest / "app" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "__init__.py").write_text("")
    (auth_dir / "resolver.py").write_text(RESOLVER)
    (auth_dir / "public.py").write_text(PUBLIC)
    remote_dir = dest / "app" / "remote"
    remote_dir.mkdir(parents=True)
    (remote_dir / "__init__.py").write_text("")
    (remote_dir / "notes.py").write_text(GUARDED_REMOTE)
    (dest / "app" / "templates" / "home" / "index.svelte").write_text(TEMPLATE)
    BuildPipeline(project_root=dest).build(dev=False)
    return dest


@pytest.fixture()
def app(built_app):
    from fymo import create_app
    from fymo.auth.identity import reset_identity_resolvers
    from fymo.auth.public import reset_public_identity

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    application = create_app(built_app, dev=False)
    yield application
    application.shutdown()
    reset_identity_resolvers()
    reset_public_identity()
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def _get(app, path, headers=None):
    responses = []

    def start_response(status, hdrs):
        responses.append((status, hdrs))

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    body = b"".join(app(environ, start_response))
    status, hdrs = responses[0]
    return status, dict(hdrs), body


def _post_remote(app, path, args, headers=None):
    payload = base64.urlsafe_b64encode(
        devalue.stringify(args).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    raw = json.dumps({"payload": payload}).encode()
    responses = []

    def start_response(status, hdrs):
        responses.append((status, hdrs))

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_HOST": "localhost",
        "HTTP_ORIGIN": "http://localhost",
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(raw), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    body = b"".join(app(environ, start_response))
    return responses[0][0], json.loads(body)


def test_signed_in_ssr_renders_identity_and_embeds_island(app):
    status, _, body = _get(app, "/", headers={"x-user": "u42"})
    assert status == "200 OK"
    html = body.decode()
    # SSR: the sidecar rendered the $identity branch server-side.
    assert "Hi user-u42" in html
    assert "Sign in" not in html
    # Hydration payload: the projection crossed as the fymo-identity island.
    assert (
        '<script type="application/json" id="fymo-identity">'
        '{"uid": "u42", "name": "user-u42"}</script>'
    ) in html


def test_anonymous_ssr_renders_signin_branch_and_null_island(app):
    status, _, body = _get(app, "/")
    assert status == "200 OK"
    html = body.decode()
    assert "Sign in" in html
    assert "Hi user-" not in html
    assert '<script type="application/json" id="fymo-identity">null</script>' in html


def test_soft_nav_envelope_carries_identity(app):
    status, _, body = _get(app, "/_fymo/data/home", headers={"x-user": "u42"})
    assert status.startswith("200")
    envelope = json.loads(body)
    assert envelope["type"] == "result"
    data = devalue.parse(envelope["result"])
    assert data["identity"] == {"uid": "u42", "name": "user-u42"}


def test_soft_nav_envelope_identity_null_when_anonymous(app):
    status, _, body = _get(app, "/_fymo/data/home")
    envelope = json.loads(body)
    data = devalue.parse(envelope["result"])
    assert data["identity"] is None


def test_unauthenticated_remote_envelope_points_at_signin(app, built_app):
    manifest = json.loads((built_app / "dist" / "manifest.json").read_text())
    notes_hash = manifest["remote_modules"]["notes"]["hash"]
    status, envelope = _post_remote(app, f"/_fymo/remote/{notes_hash}/secret_note", [])
    assert status.startswith("200")
    assert envelope["type"] == "error"
    assert envelope["status"] == 401
    assert envelope["error"] == "unauthenticated"
    assert envelope["signin"] == "/signin"


def test_signed_in_remote_call_succeeds(app, built_app):
    manifest = json.loads((built_app / "dist" / "manifest.json").read_text())
    notes_hash = manifest["remote_modules"]["notes"]["hash"]
    status, envelope = _post_remote(
        app, f"/_fymo/remote/{notes_hash}/secret_note", [], headers={"x-user": "u1"}
    )
    assert envelope["type"] == "result"
    assert devalue.parse(envelope["result"]) == "the note"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_bundle_with_identity_store_hydrates_cleanly(app, built_app):
    """The compiled client bundle (which imports $fymo/auth and seeds the
    store from the island before hydrate()) must hydrate the anonymous SSR
    HTML with zero console errors/warnings, same jsdom harness as
    tests/integration/test_hydration_real.py."""
    from fymo.server.dev import make_dev_server

    port = _free_port()
    server = make_dev_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proc = subprocess.run(
            ["node", str(HYDRATION_CHECK_JS), f"http://127.0.0.1:{port}/", str(built_app / "dist")],
            capture_output=True, text=True, timeout=30,
        )
        lines = proc.stdout.strip().splitlines()
        assert lines, f"hydration_check.mjs produced no output.\nstderr: {proc.stderr}"
        result = json.loads(lines[-1])
        assert result["errors"] == [], result
        assert result["warnings"] == [], result
        assert result["ok"] is True, result
    finally:
        server.shutdown()
        thread.join(timeout=5)
