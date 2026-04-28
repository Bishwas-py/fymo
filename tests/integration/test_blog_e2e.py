"""End-to-end: build the blog, hit /, hit /posts/<slug>, exercise a remote call."""
import base64
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


def _wsgi_call(app, path: str, *, method: str = "GET", body: bytes = b"", cookies: str = ""):
    responses = []
    def sr(s, h): responses.append((s, h))
    out = b"".join(app({
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], out


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _remote_call(app, hash_, fn_name, args, cookies: str = ""):
    """Call /_fymo/remote/<hash>/<fn> using the new wire format.

    Returns ((status, headers), envelope_dict).
    """
    body_payload = json.dumps({"payload": _b64url(devalue.stringify(args))}).encode()
    responses = []
    def sr(s, h): responses.append((s, h))
    out = b"".join(app({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"/_fymo/remote/{hash_}/{fn_name}",
        "CONTENT_LENGTH": str(len(body_payload)),
        "CONTENT_TYPE": "application/json",
        "QUERY_STRING": "",
        "HTTP_HOST": "x",
        "HTTP_ORIGIN": "http://x",
        "HTTP_COOKIE": cookies,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body_payload), "wsgi.errors": sys.stderr,
    }, sr))
    return responses[0], json.loads(out)


def _extract_uid_cookie(headers) -> str:
    for k, v in headers:
        if k.lower() == "set-cookie" and "fymo_uid=" in v:
            return v.split(";")[0]
    return ""


@pytest.mark.usefixtures("node_available")
def test_blog_e2e(blog_app: Path):
    import sys as _sys
    # Evict any stale app.* modules loaded by earlier tests (e.g. from todo_app).
    for _k in list(_sys.modules):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]

    from fymo.build.pipeline import BuildPipeline
    from app.lib.seeder import ensure_seeded

    ensure_seeded(blog_app)
    BuildPipeline(project_root=blog_app).build(dev=False)

    # Pull the per-module hash from the manifest after build.
    manifest = json.loads((blog_app / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["posts"]["hash"]

    from fymo import create_app
    app = create_app(blog_app)
    try:
        # Index renders
        (status, _), html = _wsgi_call(app, "/")
        assert status.startswith("200"), status
        assert b"fymo" in html.lower() or b"Welcome" in html or b"Blog" in html

        # Post detail renders with SSR'd HTML
        (status, _), html = _wsgi_call(app, "/posts/welcome-to-fymo")
        assert status.startswith("200"), status
        assert b"Welcome to Fymo" in html

        # Remote call: get_posts
        (status, _), env = _remote_call(app, hash_, "get_posts", [])
        assert status.startswith("200"), status
        assert env["type"] == "result"
        posts = devalue.parse(env["result"])
        slugs = [p["slug"] for p in posts]
        assert "welcome-to-fymo" in slugs

        # Remote call: create_comment with valid input
        (status, headers), env = _remote_call(
            app, hash_, "create_comment",
            ["welcome-to-fymo", {"name": "Alex", "body": "Great post"}],
        )
        assert status.startswith("200"), status
        assert env["type"] == "result"
        comment = devalue.parse(env["result"])
        assert comment["name"] == "Alex"
        uid_cookie = _extract_uid_cookie(headers)

        # Remote call: create_comment with invalid input → envelope error 422
        (status, _), env = _remote_call(
            app, hash_, "create_comment",
            ["welcome-to-fymo", {"name": "", "body": ""}],
        )
        assert status.startswith("200"), status
        assert env["type"] == "error"
        assert env["status"] == 422
        assert env["error"] == "validation"

        # Remote call: toggle_reaction (with the same uid for idempotency)
        (status, _), env = _remote_call(
            app, hash_, "toggle_reaction",
            ["welcome-to-fymo", "clap"],
            cookies=uid_cookie,
        )
        assert status.startswith("200"), status
        assert env["type"] == "result"
        counts = devalue.parse(env["result"])
        assert counts["clap"] == 1

        # Toggle again with same uid → 0
        (status, _), env = _remote_call(
            app, hash_, "toggle_reaction",
            ["welcome-to-fymo", "clap"],
            cookies=uid_cookie,
        )
        assert status.startswith("200"), status
        assert env["type"] == "result"
        counts2 = devalue.parse(env["result"])
        assert counts2["clap"] == 0
    finally:
        if app.sidecar:
            app.sidecar.stop()
