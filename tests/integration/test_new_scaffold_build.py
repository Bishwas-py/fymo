"""`fymo new` output builds as-is (issue #80 phase 5).

The default scaffold ships working password auth plus a signin page, so a
real BuildPipeline run over it proves the whole chain in one shot: remote
discovery sees app/remote/auth.py, codegen emits $remote/auth, the signin
template compiles against $remote/auth and $auth, and every hygiene
check passes with zero configuration. The signup/login/current_uid flow on
this exact file set is already covered end to end by
tests/cli/test_generate_auth.py (fymo new renders the same templates
through the same code path, pinned byte-for-byte in tests/cli/test_new.py),
so this module only needs to prove the one-shot build.

node_modules is symlinked from examples/blog_app (the known-good install
whose package.json the scaffold mirrors), same convention as
tests/integration/test_fresh_install_smoke.py.
"""
import json
import sys
from pathlib import Path

import pytest

from fymo.build.pipeline import BuildPipeline
from fymo.cli.commands.new import create_project
from tests.conftest import BLOG_APP


def _cleanup_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _clean():
    from fymo.auth import context as auth_context
    from fymo.auth.identity import reset_identity_resolvers
    from fymo.auth.public import reset_public_identity

    yield
    reset_identity_resolvers()
    reset_public_identity()
    auth_context.reset_identity_extras_hooks()
    _cleanup_app_modules()


def _scaffold(tmp_path: Path, auth: bool) -> Path:
    nm = BLOG_APP / "node_modules"
    if not nm.is_dir():
        pytest.skip("examples/blog_app/node_modules not found; run npm install in examples/blog_app/")
    create_project("myapp", auth=auth)
    project = tmp_path / "myapp"
    (project / "node_modules").symlink_to(nm)
    return project


@pytest.mark.usefixtures("node_available")
def test_default_scaffold_builds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _scaffold(tmp_path, auth=True)

    BuildPipeline(project_root=project).build(dev=False)

    assert (project / "dist" / "manifest.json").is_file()
    assert (project / "dist" / "sidecar.mjs").is_file()
    manifest = json.loads((project / "dist" / "manifest.json").read_text())
    assert any("signin" in name for name in manifest["routes"]), manifest["routes"].keys()
    assert set(manifest["remote_modules"]["auth"]["fns"]) == {"signup", "login", "logout", "me"}
    assert (project / "dist" / "client" / "_remote" / "auth.js").is_file()
    assert (project / "dist" / "client" / "_auth.js").is_file()

    # A green build is not enough: scaffold-only files (signin controller
    # and template) can build clean and still 500 at request time, e.g. a
    # top-level $remote value import fails only when the SSR module loads.
    # One real request pins the zero-step promise at the level it is made.
    import io

    from fymo import create_app

    _cleanup_app_modules()
    app = create_app(project, dev=True)
    try:
        responses = []
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/signin",
            "QUERY_STRING": "",
            "REMOTE_ADDR": "127.0.0.1",
            "SERVER_NAME": "localhost", "SERVER_PORT": "8000",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr,
            "wsgi.url_scheme": "http",
        }
        body = b"".join(app(environ, lambda s, h: responses.append((s, h))))
        status = responses[0][0]
        assert status == "200 OK", (status, body[:200])
        assert b"<form" in body
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_no_auth_scaffold_builds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = _scaffold(tmp_path, auth=False)

    BuildPipeline(project_root=project).build(dev=False)

    assert (project / "dist" / "manifest.json").is_file()
    manifest = json.loads((project / "dist" / "manifest.json").read_text())
    assert not any("signin" in name for name in manifest["routes"])
    assert manifest["remote_modules"] == {}
