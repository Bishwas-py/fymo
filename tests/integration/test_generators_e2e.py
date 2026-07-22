"""The issue #89 bar, end to end: `fymo new` + `fymo generate resource`
gives a routed page, a remote module, and passing generated tests, with
every generated line being ordinary app code.

Two resources are generated on one scaffold to cover both route paths:
`posts` is already routed by the scaffold's resources entry (the
generator reports it and touches nothing), `articles` is injected into
fymo.yml's routes block. One real BuildPipeline run then proves remote
discovery sees the generated modules, both pages SSR 200 through
create_app, and the generated app-side tests pass under a real pytest
run in the app directory (subprocess, so the app's `app` package never
collides with other tests' modules).

node_modules is symlinked from examples/blog_app, same convention as
tests/integration/test_new_scaffold_build.py.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fymo.build.pipeline import BuildPipeline
from fymo.cli.commands.new import create_project
from fymo.cli.commands.generators import generate_resource
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


def _get(app, path: str):
    responses = []
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr,
        "wsgi.url_scheme": "http",
    }
    body = b"".join(app(environ, lambda s, h: responses.append((s, h))))
    return responses[0][0], body


@pytest.mark.usefixtures("node_available")
def test_new_plus_generate_resource_builds_routes_and_tests_pass(tmp_path, monkeypatch):
    nm = BLOG_APP / "node_modules"
    if not nm.is_dir():
        pytest.skip("examples/blog_app/node_modules not found; run npm install in examples/blog_app/")
    monkeypatch.chdir(tmp_path)
    create_project("blog")
    project = tmp_path / "blog"
    (project / "node_modules").symlink_to(nm)

    monkeypatch.chdir(project)
    generate_resource("posts")
    generate_resource("articles")

    # posts was already routed by the scaffold's resources entry; articles
    # was injected into the resources list so its detail URLs exist too.
    fymo_yml = (project / "fymo.yml").read_text()
    data_routes = __import__("yaml").safe_load(fymo_yml)["routes"]
    assert "posts" not in data_routes
    assert "articles" not in data_routes
    assert data_routes["resources"] == ["articles", "posts"]

    BuildPipeline(project_root=project).build(dev=False)

    manifest = json.loads((project / "dist" / "manifest.json").read_text())
    assert set(manifest["remote_modules"]["posts"]["fns"]) == {
        "list_posts", "get_post", "create_post", "update_post", "delete_post",
    }
    assert set(manifest["remote_modules"]["articles"]["fns"]) == {
        "list_articles", "get_article", "create_article", "update_article", "delete_article",
    }
    assert (project / "dist" / "client" / "_remote" / "posts.js").is_file()

    _cleanup_app_modules()
    from fymo import create_app

    app = create_app(project, dev=True)
    try:
        status, body = _get(app, "/posts")
        assert status == "200 OK", (status, body[:200])
        assert b"Posts" in body
        status, body = _get(app, "/articles")
        assert status == "200 OK", (status, body[:200])
        assert b"Articles" in body
        # Detail URLs resolve through the resources expansion and render
        # the show view (index.svelte branches to the co-located
        # show.svelte on the id param; its file chip is stable SSR text).
        status, body = _get(app, "/posts/1")
        assert status == "200 OK", (status, body[:200])
        assert b"app/templates/posts/show.svelte" in body
        status, body = _get(app, "/articles/1")
        assert status == "200 OK", (status, body[:200])
        assert b"app/templates/articles/show.svelte" in body
    finally:
        app.shutdown()

    # The generated tests pass unedited, run the way the developer would
    # run them: pytest in the app directory.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/test_posts_remote.py", "tests/test_articles_remote.py"],
        cwd=project, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "18 passed" in result.stdout
