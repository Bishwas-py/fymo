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
