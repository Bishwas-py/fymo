"""End-to-end: build the blog, hit /, hit /posts/<id>, exercise the generated CRUD remotes with real auth."""
import base64
import io
import json
import sys
from pathlib import Path
import pytest

from fymo.remote import devalue


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


def _extract_cookie(headers, name) -> str:
    for k, v in headers:
        if k.lower() == "set-cookie" and v.startswith(f"{name}="):
            return v.split(";")[0]
    return ""


def _extract_uid_cookie(headers) -> str:
    return _extract_cookie(headers, "fymo_uid")


@pytest.mark.usefixtures("node_available")
def test_blog_e2e(blog_app: Path):
    import sys as _sys
    # Evict any stale app.* modules loaded by earlier tests (e.g. from todo_app).
    for _k in list(_sys.modules):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]

    from fymo.build.pipeline import BuildPipeline

    BuildPipeline(project_root=blog_app).build(dev=False)

    # Pull the per-module hashes from the manifest after build.
    manifest = json.loads((blog_app / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["posts"]["hash"]
    # blog_app owns its auth endpoints (app/remote/auth.py, scaffolded by
    # `fymo generate auth`), so its client ships like any other module.
    auth_hash = manifest["remote_modules"]["auth"]["hash"]

    from fymo import create_app
    app = create_app(blog_app)
    try:
        # Home renders (the scaffold proof board).
        (status, _), html = _wsgi_call(app, "/")
        assert status.startswith("200"), status
        assert b"It's alive." in html

        # Post detail renders with SSR'd HTML: the generated show view
        # reached through the resources route, seed row id 1.
        (status, _), html = _wsgi_call(app, "/posts/1")
        assert status.startswith("200"), status
        assert b"app/templates/posts/show.svelte" in html

        # Remote call: list_posts sees the seed row.
        (status, _), env = _remote_call(app, hash_, "list_posts", [])
        assert status.startswith("200"), status
        assert env["type"] == "result"
        posts = devalue.parse(env["result"])
        assert any(row["id"] == 1 and row["created_by"] == "seed" for row in posts)

        # Mutations are gated: an anonymous create_post is rejected.
        (status, _), env = _remote_call(app, hash_, "create_post", ["First!"])
        assert env["type"] == "error"
        assert env["status"] == 401
        assert env["error"] == "unauthenticated"

        # Sign up via the app-owned auth endpoints to obtain a session.
        (_, signup_headers), env = _remote_call(
            app, auth_hash, "signup", ["alex@example.com", "longpassword"],
        )
        assert env["type"] == "result", env
        signup_uid = devalue.parse(env["result"])["uid"]
        session_cookie = _extract_cookie(signup_headers, "session")
        uid_cookie = _extract_cookie(signup_headers, "fymo_uid")
        assert session_cookie
        auth_cookies = f"{uid_cookie}; {session_cookie}"

        # Authenticated create_post succeeds; the author comes from the
        # authenticated identity, never client input.
        (status, _), env = _remote_call(
            app, hash_, "create_post", ["Hello from e2e"], cookies=auth_cookies,
        )
        assert status.startswith("200"), status
        assert env["type"] == "result", env
        created = devalue.parse(env["result"])
        assert created["created_by"] == signup_uid

        # The owner can rename it through the same dispatch.
        (status, _), env = _remote_call(
            app, hash_, "update_post", [created["id"], "Renamed"], cookies=auth_cookies,
        )
        assert env["type"] == "result", env
        assert devalue.parse(env["result"])["title"] == "Renamed"

        # Anonymous update of the same row: 401 before any ownership check.
        (status, _), env = _remote_call(app, hash_, "update_post", [created["id"], "steal"])
        assert env["type"] == "error"
        assert env["status"] == 401

        # Unknown id answers the NotFound envelope.
        (status, _), env = _remote_call(app, hash_, "get_post", [999])
        assert env["type"] == "error"
        assert env["status"] == 404
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_home_page_gets_root_layout_head(blog_app: Path):
    """The root layout wraps every route: its <svelte:head> favicon link
    must land in the rendered HTML of a page that never mentions it."""
    import subprocess
    subprocess.run(["fymo", "build"], cwd=blog_app, check=True, capture_output=True)
    from fymo import create_app
    app = create_app(blog_app)
    try:
        (status, headers), out = _wsgi_call(app, "/")
        html = out.decode("utf-8")
        assert status == "200 OK"
        assert 'rel="icon"' in html
        assert 'href="/favicon.svg"' in html
    finally:
        if app.sidecar:
            app.sidecar.stop()
