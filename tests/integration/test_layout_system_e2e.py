"""End-to-end: build blog_app (migrated to use _layout.svelte in Task 11),
verify SSR HTML, manifest shape, and soft-nav payload agree on the layout
system across a full page load AND a soft-nav.
"""
import json
import subprocess
from pathlib import Path
import pytest

from fymo.remote import devalue


@pytest.fixture
def blog_app(tmp_path: Path):
    import shutil, sys
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    BLOG_DIR = REPO_ROOT / "examples" / "blog_app"
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
        "CONTENT_LENGTH": "0", "CONTENT_TYPE": "", "HTTP_COOKIE": "",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": __import__("io").BytesIO(b""), "wsgi.errors": __import__("sys").stderr,
        "wsgi.url_scheme": "http",
    }, sr))
    return responses[0][0], out


@pytest.mark.usefixtures("node_available")
def test_full_layout_system_end_to_end(blog_app: Path):
    subprocess.run(["fymo", "build"], cwd=blog_app, check=True, capture_output=True)

    from fymo.build.manifest import Manifest
    manifest = Manifest.read(blog_app / "dist" / "manifest.json")

    # 1. Manifest shape: root layout applies to every route. Task 11's
    #    migration only added examples/blog_app/app/templates/_layout.svelte
    #    (a root layout) -- there is no posts/_layout.svelte or
    #    tags/_layout.svelte, so every route's layout_chain has exactly one
    #    "root" entry and no "resource" entry.
    assert "_root" in manifest.layouts
    for route_name in ("index", "posts", "tags"):
        route = manifest.routes[route_name]
        assert route.uses_layout_shell is True
        assert [ref.level for ref in route.layout_chain] == ["root"]

    # 2. Full-page SSR includes Nav (from the layout) exactly once.
    # FymoApp is itself the WSGI callable (implements __call__) -- there is
    # no separate `.wsgi_app` attribute, so we call the instance directly.
    from fymo.core.server import FymoApp
    app = FymoApp(blog_app, dev=False)
    status, out = _wsgi_get(app, "/")
    assert status == "200 OK"
    html = out.decode("utf-8")
    assert html.count("<nav") == 1

    # 3. Soft-nav to a post reports usesLayoutShell + omits resourceLayout
    #    (no posts/_layout.svelte in this migration), and rootLayoutProps
    #    is present ({} since the root layout has no controller).
    from app.lib.seeder import ensure_seeded
    ensure_seeded(blog_app)
    status, out = _wsgi_get(app, "/_fymo/data/posts/welcome-to-fymo")
    payload = json.loads(out)
    decoded = devalue.parse(payload["result"])
    assert decoded["leaf"]["usesLayoutShell"] is True
    assert decoded["leaf"]["resourceLayout"] is None
    assert decoded["leaf"]["rootLayoutProps"] == {}

    # 4. The generated client shell for "index" actually contains the
    #    reactive-swap exports, proving Task 5's codegen ran for this route.
    shell_path = blog_app / ".fymo" / "entries" / "index.shell.svelte"
    assert shell_path.is_file()
    shell_content = shell_path.read_text()
    assert "export function swapLeaf" in shell_content
    assert "unmount" not in shell_content
