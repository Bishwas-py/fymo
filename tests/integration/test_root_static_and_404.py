"""Root-static allowlist, /static/ serving, + built-in 404 through the full
WSGI dispatch (issues #75, #77).

Precedence pinned here: app raw routes (app/routes.py) win over the root
allowlist, which wins over the built-in 404. Unknown routes are a 404 with
a mode-appropriate body, never a 500. app/static/ files serve at /static/;
/assets/ no longer exists and falls through to the 404 path.
"""
import io
import shutil
import sys
from pathlib import Path

import pytest

from fymo.build.pipeline import BuildPipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TODO_APP = REPO_ROOT / "examples" / "todo_app"

# Real .ico magic (ICONDIR: reserved=0, type=1, count=1) plus bytes that are
# not valid UTF-8, so a decode() regression turns these tests red.
ICO_BYTES = b"\x00\x00\x01\x00\x01\x00" + bytes(range(250, 256)) * 4


@pytest.fixture(scope="module")
def built_app(tmp_path_factory, node_available):
    """One built copy of examples/todo_app shared by the whole module.

    Static files are read from disk per request, so tests may add files
    under app/static/ freely; anything that changes what FymoApp discovers
    at init (app/routes.py) must build its own app and clean up after.
    """
    dest = tmp_path_factory.mktemp("root_static") / "todo_app"
    shutil.copytree(
        TODO_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo")
    )
    nm = TODO_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/todo_app/node_modules not found — run npm install in examples/todo_app/")
    (dest / "app" / "static").mkdir(parents=True, exist_ok=True)
    BuildPipeline(project_root=dest).build(dev=False)
    return dest


@pytest.fixture(scope="module")
def prod_app(built_app):
    from fymo import create_app
    app = create_app(built_app, dev=False)
    yield app
    app.shutdown()


def _get(app, path, extra_environ=None):
    responses = []

    def start_response(status, headers):
        responses.append((status, headers))

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }
    if extra_environ:
        environ.update(extra_environ)
    body = b"".join(app(environ, start_response))
    status, headers = responses[0]
    return status, dict(headers), body


def test_unknown_route_is_404_with_clean_body_in_prod(prod_app):
    status, headers, body = _get(prod_app, "/no-such-page")
    assert status == "404 NOT FOUND"
    assert headers["Content-Type"] == "text/html"
    text = body.decode("utf-8")
    assert "404" in text
    for leak in ("fymo build", "manifest", "No route matched", "config/routes"):
        assert leak not in text


def test_unknown_route_shows_routing_hint_in_dev(built_app):
    from fymo import create_app
    app = create_app(built_app, dev=True)
    try:
        status, _, body = _get(app, "/no-such-page")
        assert status == "404 NOT FOUND"
        text = body.decode("utf-8")
        assert "No route matched" in text
        assert "/no-such-page" in text
    finally:
        app.shutdown()


def test_favicon_ico_served_from_app_static(built_app, prod_app):
    (built_app / "app" / "static" / "favicon.ico").write_bytes(ICO_BYTES)
    status, headers, body = _get(prod_app, "/favicon.ico")
    assert status == "200 OK"
    assert headers["Content-Type"] in ("image/x-icon", "image/vnd.microsoft.icon")
    assert body == ICO_BYTES


def test_favicon_conditional_request_gets_304(built_app, prod_app):
    (built_app / "app" / "static" / "favicon.ico").write_bytes(ICO_BYTES)
    _, headers, _ = _get(prod_app, "/favicon.ico")
    etag = headers["ETag"]
    status, headers, body = _get(prod_app, "/favicon.ico", {"HTTP_IF_NONE_MATCH": etag})
    assert status == "304 NOT MODIFIED"
    assert body == b""


def test_absent_allowlisted_file_is_404_never_500(prod_app):
    # robots.txt is allowlisted and the scaffold ships no robots.txt
    # (favicon.svg it does ship, so that one now really serves).
    status, _, body = _get(prod_app, "/robots.txt")
    assert status == "404 NOT FOUND"
    assert b"fymo build" not in body


def test_well_known_prefix_maps_to_app_static(built_app, prod_app):
    well_known = built_app / "app" / "static" / ".well-known"
    well_known.mkdir(exist_ok=True)
    (well_known / "security.txt").write_text("Contact: mailto:sec@example.com\n")
    status, _, body = _get(prod_app, "/.well-known/security.txt")
    assert status == "200 OK"
    assert body == b"Contact: mailto:sec@example.com\n"

    status, _, _ = _get(prod_app, "/.well-known/absent.txt")
    assert status == "404 NOT FOUND"


def test_allowlist_is_not_an_open_root_directory(built_app, prod_app):
    """Only the fixed well-known names are served at /; arbitrary files in
    app/static keep requiring the /static/ prefix."""
    (built_app / "app" / "static" / "notes.txt").write_text("not for root serving")
    status, _, body = _get(prod_app, "/notes.txt")
    assert status == "404 NOT FOUND"
    assert b"not for root serving" not in body


# Real woff2 magic + invalid UTF-8, same convention as ICO_BYTES above.
WOFF2_BYTES = b"wOF2\x00\x01\x00\x00" + bytes(range(256))


def test_static_url_serves_app_static_bytes(built_app, prod_app):
    """Issue #77: files in app/static/ serve at /static/<path>, byte-exact,
    through the same binary-correct path #74 fixed."""
    fonts = built_app / "app" / "static" / "fonts"
    fonts.mkdir(exist_ok=True)
    (fonts / "Inter.woff2").write_bytes(WOFF2_BYTES)
    status, headers, body = _get(prod_app, "/static/fonts/Inter.woff2")
    assert status == "200 OK"
    assert headers["Content-Type"] == "font/woff2"
    assert body == WOFF2_BYTES
    assert headers["ETag"].startswith('"')


def test_static_url_conditional_request_gets_304(built_app, prod_app):
    (built_app / "app" / "static" / "cached.txt").write_text("cache me")
    _, headers, _ = _get(prod_app, "/static/cached.txt")
    etag = headers["ETag"]
    status, _, body = _get(prod_app, "/static/cached.txt", {"HTTP_IF_NONE_MATCH": etag})
    assert status == "304 NOT MODIFIED"
    assert body == b""


def test_static_url_traversal_is_blocked(built_app, prod_app):
    (built_app / "secret.txt").write_text("TOP SECRET")
    status, _, body = _get(prod_app, "/static/../../secret.txt")
    assert not status.startswith("200")
    assert b"TOP SECRET" not in body


def test_assets_url_no_longer_exists(built_app, prod_app):
    """Issue #77 companion rename (absorbed #78): /assets/ is gone entirely.
    No dual serving, no redirect — the request falls through to normal
    routing and hits #75's built-in 404, even when the file exists in
    app/static/."""
    (built_app / "app" / "static" / "present.txt").write_text("reachable only at /static/")
    status, headers, body = _get(prod_app, "/assets/present.txt")
    assert status == "404 NOT FOUND"
    assert headers["Content-Type"] == "text/html"
    assert b"reachable only at /static/" not in body


def test_app_raw_route_wins_over_static_robots_txt(built_app):
    """An http_routes() entry for /robots.txt shadows app/static/robots.txt,
    keeping dynamic robots/sitemaps possible."""
    (built_app / "app" / "static" / "robots.txt").write_text("User-agent: *\nDisallow: /static-version\n")
    routes_py = built_app / "app" / "routes.py"
    routes_py.write_text(
        "from fymo.core.http import HttpRoute\n"
        "\n"
        "def _robots(environ, start_response):\n"
        "    body = b'User-agent: *\\nDisallow: /dynamic-version\\n'\n"
        "    start_response('200 OK', [('Content-Type', 'text/plain'),\n"
        "                              ('Content-Length', str(len(body)))])\n"
        "    return [body]\n"
        "\n"
        "def http_routes():\n"
        "    return [HttpRoute('GET', '/robots.txt', _robots)]\n"
    )
    from fymo import create_app
    try:
        app = create_app(built_app, dev=False)
        try:
            status, _, body = _get(app, "/robots.txt")
            assert status == "200 OK"
            assert b"dynamic-version" in body
            assert b"static-version" not in body
        finally:
            app.shutdown()
    finally:
        routes_py.unlink()


def test_static_robots_txt_served_when_no_raw_route(built_app, prod_app):
    (built_app / "app" / "static" / "robots.txt").write_text("User-agent: *\nDisallow:\n")
    status, _, body = _get(prod_app, "/robots.txt")
    assert status == "200 OK"
    assert body == b"User-agent: *\nDisallow:\n"
