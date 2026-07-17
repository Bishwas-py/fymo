"""Route-level require_auth end to end through the full WSGI dispatch
(issue #80 phase 2): app/auth/ auto-discovery at boot, the anon 302 with
?next=, the signed-in render, a dotted-path guard, the soft-nav redirect
envelope, and the boot-time hard errors (unimportable guard, missing
signin route).
"""
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

from fymo.build.pipeline import BuildPipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TODO_APP = REPO_ROOT / "examples" / "todo_app"

FYMO_YML = """\
name: todo_app
version: 1.0.0
routes:
  root: home.index
  resources:
    - name: todos
      require_auth: true
    - home
  signin: home.index
  admin:
    to: home.index
    require_auth: app.auth.guards.require_admin
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

GUARDS = """\
from fymo.auth import current_uid

def require_admin():
    if current_uid() != "admin":
        raise ValueError("admin only")
"""

# Explicit-form protected routes: root protected, and an explicit dict route
# whose path segment equals a controller with a real manifest (todos). These
# are the shapes whose convention-based aliases (/todos/index, /todos/whatever,
# /home) previously rendered the protected page anonymously.
BYPASS_YML = """\
name: todo_app
version: 1.0.0
routes:
  root:
    to: home.index
    require_auth: true
  todos:
    to: todos.index
    require_auth: true
  signin: home.index
build:
  output_dir: dist
"""


@pytest.fixture(autouse=True)
def _reset_identity_registry():
    """The identify registry is process-global; every path in this module
    (build hygiene, FymoApp boot, failed boots) imports app/auth and
    registers resolvers, so drop them after each test."""
    from fymo.auth.identity import reset_identity_resolvers

    yield
    reset_identity_resolvers()


@pytest.fixture(scope="module")
def built_app(tmp_path_factory, node_available):
    dest = tmp_path_factory.mktemp("require_auth") / "todo_app"
    shutil.copytree(
        TODO_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo")
    )
    nm = TODO_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/todo_app/node_modules not found — run npm install in examples/todo_app/")
    (dest / "fymo.yml").write_text(FYMO_YML)
    auth_dir = dest / "app" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "__init__.py").write_text("")
    (auth_dir / "resolver.py").write_text(RESOLVER)
    (auth_dir / "guards.py").write_text(GUARDS)
    BuildPipeline(project_root=dest).build(dev=False)
    return dest


@pytest.fixture()
def app(built_app):
    from fymo import create_app
    from fymo.auth.identity import reset_identity_resolvers

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    application = create_app(built_app, dev=False)
    yield application
    application.shutdown()
    reset_identity_resolvers()
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def _get(app, path, headers=None, query=""):
    responses = []

    def start_response(status, hdrs):
        responses.append((status, hdrs))

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }
    for name, value in (headers or {}).items():
        environ["HTTP_" + name.upper().replace("-", "_")] = value
    body = b"".join(app(environ, start_response))
    status, hdrs = responses[0]
    return status, dict(hdrs), body


def test_anon_protected_page_redirects_to_signin_with_next(app):
    status, headers, body = _get(app, "/todos")
    assert status.startswith("302")
    assert headers["Location"] == "/signin?next=%2Ftodos"
    assert body == b""


def test_next_carries_query_string(app):
    status, headers, _ = _get(app, "/todos", query="page=2")
    assert status.startswith("302")
    assert headers["Location"] == "/signin?next=%2Ftodos%3Fpage%3D2"


def test_signed_in_request_renders_protected_page(app):
    status, headers, body = _get(app, "/todos", headers={"x-user": "u1"})
    assert status == "200 OK"
    assert b"<html" in body.lower()


def test_public_route_stays_public(app):
    status, _, _ = _get(app, "/")
    assert status == "200 OK"


def test_guard_rejection_redirects(app):
    status, headers, _ = _get(app, "/admin", headers={"x-user": "u1"})
    assert status.startswith("302")
    assert headers["Location"] == "/signin?next=%2Fadmin"


def test_guard_pass_renders(app):
    status, _, _ = _get(app, "/admin", headers={"x-user": "admin"})
    assert status == "200 OK"


def test_soft_nav_data_endpoint_gets_redirect_envelope(app):
    status, _, body = _get(app, "/_fymo/data/todos")
    assert status.startswith("200")
    envelope = json.loads(body)
    assert envelope == {
        "type": "redirect",
        "location": "/signin?next=%2Ftodos",
        "status": 302,
    }


def test_soft_nav_data_endpoint_passes_when_signed_in(app):
    status, _, body = _get(app, "/_fymo/data/todos", headers={"x-user": "u1"})
    envelope = json.loads(body)
    assert envelope["type"] == "result"


def test_boot_fails_loudly_on_unimportable_guard(built_app):
    from fymo import create_app
    from fymo.core.exceptions import ConfigurationError

    bad_yml = FYMO_YML.replace(
        "app.auth.guards.require_admin", "app.auth.guards.no_such_guard"
    )
    original = (built_app / "fymo.yml").read_text()
    (built_app / "fymo.yml").write_text(bad_yml)
    try:
        with pytest.raises(ConfigurationError, match=r"app\.auth\.guards\.no_such_guard"):
            create_app(built_app, dev=False)
    finally:
        (built_app / "fymo.yml").write_text(original)


def test_boot_fails_loudly_when_signin_route_missing(built_app):
    from fymo import create_app
    from fymo.core.exceptions import ConfigurationError

    no_signin = FYMO_YML.replace("  signin: home.index\n", "")
    original = (built_app / "fymo.yml").read_text()
    (built_app / "fymo.yml").write_text(no_signin)
    try:
        with pytest.raises(ConfigurationError, match="signin"):
            create_app(built_app, dev=False)
    finally:
        (built_app / "fymo.yml").write_text(original)


# --------------- convention-alias bypass of route-level require_auth ---------------


@pytest.fixture(scope="module")
def bypass_app(tmp_path_factory, node_available):
    dest = tmp_path_factory.mktemp("require_auth_bypass") / "todo_app"
    shutil.copytree(
        TODO_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo")
    )
    nm = TODO_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/todo_app/node_modules not found — run npm install in examples/todo_app/")
    (dest / "fymo.yml").write_text(BYPASS_YML)
    auth_dir = dest / "app" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "__init__.py").write_text("")
    (auth_dir / "resolver.py").write_text(RESOLVER)
    BuildPipeline(project_root=dest).build(dev=False)
    return dest


@pytest.fixture()
def bapp(bypass_app):
    from fymo import create_app
    from fymo.auth.identity import reset_identity_resolvers

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    application = create_app(bypass_app, dev=False)
    yield application
    application.shutdown()
    reset_identity_resolvers()
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.mark.parametrize("path", [
    "/todos/index",
    "/todos/whatever",
    "/home",
    "/home/index",
])
def test_convention_alias_of_protected_route_redirects_anon(bapp, path):
    status, headers, body = _get(bapp, path)
    assert status.startswith("302"), f"{path} should redirect, got {status}"
    assert headers["Location"].startswith("/signin?next=")
    assert body == b""


def test_soft_nav_alias_of_protected_route_gets_redirect_envelope(bapp):
    status, _, body = _get(bapp, "/_fymo/data/todos/index")
    assert status.startswith("200")
    envelope = json.loads(body)
    assert envelope["type"] == "redirect"
    assert envelope["status"] == 302
    assert envelope["location"].startswith("/signin?next=")


def test_declared_signin_path_stays_public_despite_shared_controller(bapp):
    # signin: home.index shares the home controller with the protected root,
    # but the exact declared /signin path must stay public.
    status, _, body = _get(bapp, "/signin")
    assert status == "200 OK"
    assert b"<html" in body.lower()


def test_convention_alias_renders_for_signed_in_user(bapp):
    status, _, body = _get(bapp, "/todos/index", headers={"x-user": "u1"})
    assert status == "200 OK"
    assert b"<html" in body.lower()
