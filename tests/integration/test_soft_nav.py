"""End-to-end: GET /_fymo/data/<path> returns the leaf's bundle URLs + props."""
import io
import json
import shutil
import sys
from pathlib import Path
import pytest

from fymo.remote import devalue


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOG_DIR = REPO_ROOT / "examples" / "blog_app"


@pytest.fixture
def blog_app(tmp_path: Path):
    if not BLOG_DIR.is_dir():
        pytest.skip("blog_app missing")
    dest = tmp_path / "blog_app"
    shutil.copytree(BLOG_DIR, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo", "app/data"))
    nm = BLOG_DIR / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    sys.path.insert(0, str(dest))
    yield dest
    sys.path.remove(str(dest))
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]


def _wsgi_get(app, path: str):
    responses = []
    def sr(s, h): responses.append((s, h))
    out = b"".join(app({
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": "0", "CONTENT_TYPE": "",
        "HTTP_COOKIE": "",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], json.loads(out)


@pytest.mark.usefixtures("node_available")
def test_soft_nav_data_returns_leaf_envelope(blog_app: Path, monkeypatch):
    """Hitting /_fymo/data/posts/welcome-to-fymo returns the bundle URL + props."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from app.lib.seeder import ensure_seeded
    ensure_seeded(blog_app)
    from fymo import create_app
    app = create_app(blog_app)
    try:
        (status, headers), envelope = _wsgi_get(app, "/_fymo/data/posts/welcome-to-fymo")
        assert status.startswith("200"), status
        assert envelope["type"] == "result", envelope
        result = devalue.parse(envelope["result"])

        # leaf shape
        leaf = result["leaf"]
        assert leaf["id"] == "posts"  # controller name from fymo.yml resources
        assert leaf["module"].startswith("/dist/client/posts.")
        assert leaf["module"].endswith(".js")
        # CSS may or may not exist depending on stylesheet output
        assert isinstance(leaf["css"], list)
        # Props came from posts.getContext(id="welcome-to-fymo")
        props = leaf["props"]
        assert "post" in props
        assert props["post"]["slug"] == "welcome-to-fymo"
        # Remote callables threaded through controller props become markers
        assert isinstance(props["create_comment"], dict)
        assert "__fymo_remote" in props["create_comment"]

        # title from getDoc()
        assert "title" in result
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_soft_nav_unknown_route_returns_no_route(blog_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from app.lib.seeder import ensure_seeded
    ensure_seeded(blog_app)
    from fymo import create_app
    app = create_app(blog_app)
    try:
        (status, _), envelope = _wsgi_get(app, "/_fymo/data/this/does/not/exist")
        assert status.startswith("200")
        assert envelope["type"] == "error"
        # Either no_route (router miss) or no_controller (router fell through to convention)
        assert envelope["error"] in ("no_route", "no_controller", "no_bundle")
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_soft_nav_root_path(blog_app: Path, monkeypatch):
    """`/_fymo/data/` (root) should resolve to the root route."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from app.lib.seeder import ensure_seeded
    ensure_seeded(blog_app)
    from fymo import create_app
    app = create_app(blog_app)
    try:
        (status, _), envelope = _wsgi_get(app, "/_fymo/data/")
        assert status.startswith("200"), envelope
        assert envelope["type"] == "result"
        result = devalue.parse(envelope["result"])
        assert result["leaf"]["id"] == "index"
    finally:
        if app.sidecar:
            app.sidecar.stop()


_WHOAMI_CONTROLLER = '''"""Whoami controller: exercises current_user() during soft-nav."""
from fymo.auth.context import current_user


def getContext():
    user = current_user()
    return {"email": user.email if user else None}
'''

_WHOAMI_TEMPLATE = """<script>
  let { email } = $props();
</script>

<div>
  {#if email}
    <p data-testid="whoami">Logged in as {email}</p>
  {:else}
    <p data-testid="whoami">Not logged in</p>
  {/if}
</div>
"""


@pytest.fixture
def whoami_blog_app(blog_app: Path):
    """blog_app plus a `whoami` route whose controller calls current_user()."""
    (blog_app / "app" / "controllers" / "whoami.py").write_text(_WHOAMI_CONTROLLER)
    tpl_dir = blog_app / "app" / "templates" / "whoami"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "index.svelte").write_text(_WHOAMI_TEMPLATE)

    fymo_yml = blog_app / "fymo.yml"
    text = fymo_yml.read_text()
    assert "    - tags\n" in text, "unexpected fymo.yml shape in examples/blog_app"
    text = text.replace("    - tags\n", "    - tags\n    - whoami\n")
    fymo_yml.write_text(text)
    return blog_app


@pytest.mark.usefixtures("node_available")
def test_soft_nav_sees_logged_in_user_from_session_cookie(whoami_blog_app: Path):
    """The soft-nav data endpoint must give current_user() the same request
    scope the full-page SSR path gets -- this is the C1 gap: previously this
    500'd with `controller_failed` because current_user() was called outside
    of any request scope on the soft-nav path.
    """
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=whoami_blog_app).build(dev=False)

    from fymo import create_app
    from fymo.auth.session import make_session_token

    app = create_app(whoami_blog_app)
    try:
        user = app.user_store.create("soft-nav@example.com", None)
        token = make_session_token(user.id, user.session_epoch)

        responses = []

        def sr(s, h):
            responses.append((s, h))

        out = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/_fymo/data/whoami", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "CONTENT_TYPE": "",
            "HTTP_COOKIE": f"fymo_session={token}",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr))
        (status, _headers) = responses[0]
        envelope = json.loads(out)

        assert status.startswith("200"), envelope
        assert envelope["type"] == "result", envelope
        result = devalue.parse(envelope["result"])
        assert result["leaf"]["props"]["email"] == "soft-nav@example.com"
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_soft_nav_logged_out_has_no_user_and_does_not_500(whoami_blog_app: Path):
    """No session cookie -> current_user() is None, props carry email: None,
    and the endpoint must not 500."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=whoami_blog_app).build(dev=False)

    from fymo import create_app

    app = create_app(whoami_blog_app)
    try:
        (status, _headers), envelope = _wsgi_get(app, "/_fymo/data/whoami")
        assert status.startswith("200"), envelope
        assert envelope["type"] == "result", envelope
        result = devalue.parse(envelope["result"])
        assert result["leaf"]["props"]["email"] is None
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_soft_nav_disabled_resource_returns_error_envelope(blog_app: Path, monkeypatch):
    """Resources with `soft_nav: false` in fymo.yml respond with the opt-out envelope."""
    fymo_yml = blog_app / "fymo.yml"
    fymo_yml.write_text(
        "name: blog_app\n"
        "version: 1.0.0\n"
        "routes:\n"
        "  root: index.index\n"
        "  resources:\n"
        "    - name: posts\n"
        "      soft_nav: false\n"
        "    - tags\n"
        # auth stays enabled so the blog's generated $remote/auth client (which
        # app/lib/auth.ts imports) is produced during the build.
        "auth:\n"
        "  enabled: true\n"
        "build:\n"
        "  output_dir: dist\n"
    )

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from app.lib.seeder import ensure_seeded
    ensure_seeded(blog_app)
    from fymo import create_app
    app = create_app(blog_app)
    try:
        (status, _), env = _wsgi_get(app, "/_fymo/data/posts/welcome-to-fymo")
        assert status.startswith("200")
        assert env["type"] == "error"
        assert env["error"] == "soft_nav_disabled"
        assert env["status"] == 409

        (status, _), env = _wsgi_get(app, "/_fymo/data/tags")
        assert status.startswith("200")
        assert env["type"] == "result", env
    finally:
        if app.sidecar:
            app.sidecar.stop()


def test_soft_nav_reports_layout_shell_for_migrated_root_only_route(blog_app: Path, node_available):
    """blog_app's root route has only a root _layout.svelte (no resource-level
    layout, no _layout.py controller). Its leaf payload must say
    usesLayoutShell=True so the client can drive the shell that was hydrated,
    while resourceLayout stays None (no resource layout exists) and
    rootLayoutProps is an empty dict (no controller means load_layout_props_and_docs
    yields {} rather than None)."""
    import subprocess
    subprocess.run(["fymo", "build"], cwd=blog_app, check=True, capture_output=True)
    from fymo.core.server import FymoApp
    app = FymoApp(blog_app, dev=False)
    (status, _), payload = _wsgi_get(app, "/_fymo/data/")
    assert payload["type"] == "result"
    decoded = devalue.parse(payload["result"])
    assert decoded["leaf"]["usesLayoutShell"] is True
    assert decoded["leaf"]["resourceLayout"] is None
    assert decoded["leaf"]["rootLayoutProps"] == {}


def test_soft_nav_includes_resource_layout_for_layout_routes(blog_app: Path, node_available):
    templates = blog_app / "app" / "templates"
    (templates / "_layout.svelte").write_text(
        "<script>\n  let { children } = $props();\n</script>\n{@render children()}\n"
    )
    (templates / "posts" / "_layout.svelte").write_text(
        "<script>\n  let { children } = $props();\n</script>\n{@render children()}\n"
    )
    import subprocess
    subprocess.run(["fymo", "build"], cwd=blog_app, check=True, capture_output=True)
    from fymo.core.server import FymoApp
    app = FymoApp(blog_app, dev=False)

    from app.lib.seeder import ensure_seeded
    ensure_seeded(blog_app)

    (status, _), payload = _wsgi_get(app, "/_fymo/data/posts/welcome-to-fymo")
    decoded = devalue.parse(payload["result"])
    assert decoded["leaf"]["usesLayoutShell"] is True
    assert decoded["leaf"]["resourceLayout"]["id"] == "posts"
    assert decoded["leaf"]["resourceLayout"]["module"].startswith("/dist/")
    assert decoded["leaf"]["rootLayoutProps"] == {}
