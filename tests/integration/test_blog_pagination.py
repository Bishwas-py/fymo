"""End-to-end: fymo.remote.pagination through real dispatch.

The old blog example carried a db-backed paginated list_posts; the
regenerated example is in-memory with no pagination, so the paginated
module is test-owned now: written onto the blog copy, discovered and
dispatched through the real remote router exactly as before, with the
same (published_at, slug) tiebreak shape the old example taught.
"""
import base64
import io
import json
import sys
from pathlib import Path
import pytest

from fymo.remote import devalue

_FEED_REMOTE = '''"""Test-owned paginated remote over in-memory rows."""
from typing import TypedDict

from fymo.remote import decode_cursor, paginate, remote


class Entry(TypedDict):
    slug: str
    published_at: str


class FeedPage(TypedDict):
    items: list[Entry]
    next_cursor: str | None


_ROWS: list[Entry] = [
    {"slug": "post-e", "published_at": "2026-01-05T00:00:00Z"},
    {"slug": "post-d", "published_at": "2026-01-04T00:00:00Z"},
    {"slug": "post-c2", "published_at": "2026-01-03T00:00:00Z"},
    {"slug": "post-c1", "published_at": "2026-01-03T00:00:00Z"},
    {"slug": "post-a", "published_at": "2026-01-01T00:00:00Z"},
]


@remote
def list_feed(cursor: str | None = None, limit: int = 20) -> FeedPage:
    # Cursor pagination over (published_at, slug): published_at alone is
    # not unique, so slug breaks ties. Hand paginate() one row past
    # `limit`; the extra row becomes next_cursor (null on the last page).
    limit = max(1, min(limit, 50))
    rows = sorted(_ROWS, key=lambda r: (r["published_at"], r["slug"]), reverse=True)
    if cursor:
        published_at, slug = decode_cursor(cursor, expect=2)
        rows = [r for r in rows if (r["published_at"], r["slug"]) < (published_at, slug)]
    return paginate(rows[: limit + 1], limit, key=lambda r: (r["published_at"], r["slug"]))
'''


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _remote_call(app, hash_, fn_name, args):
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
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body_payload), "wsgi.errors": sys.stderr,
    }, sr))
    return responses[0], json.loads(out)


@pytest.fixture
def paginated_blog(blog_app: Path) -> Path:
    (blog_app / "app" / "remote" / "feed.py").write_text(_FEED_REMOTE)
    return blog_app


@pytest.mark.usefixtures("node_available")
def test_list_feed_pages_through_to_the_end(paginated_blog: Path):
    for _k in list(sys.modules):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]

    from fymo.build.pipeline import BuildPipeline

    BuildPipeline(project_root=paginated_blog).build(dev=False)
    manifest = json.loads((paginated_blog / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["feed"]["hash"]

    from fymo import create_app
    app = create_app(paginated_blog)
    try:
        # Page 1: no cursor.
        (status, _), env = _remote_call(app, hash_, "list_feed", [None, 2])
        assert status.startswith("200")
        assert env["type"] == "result"
        page1 = devalue.parse(env["result"])
        assert [p["slug"] for p in page1["items"]] == ["post-e", "post-d"]
        assert page1["next_cursor"]

        # Page 2: same-date rows ordered by slug DESC.
        (_, _), env = _remote_call(app, hash_, "list_feed", [page1["next_cursor"], 2])
        page2 = devalue.parse(env["result"])
        assert [p["slug"] for p in page2["items"]] == ["post-c2", "post-c1"]
        assert page2["next_cursor"]

        # Page 3: last row, next_cursor null.
        (_, _), env = _remote_call(app, hash_, "list_feed", [page2["next_cursor"], 2])
        page3 = devalue.parse(env["result"])
        assert [p["slug"] for p in page3["items"]] == ["post-a"]
        assert page3["next_cursor"] is None

        # The generated client sends every positional slot; an argless call
        # arrives as [undefined, undefined] and must use the defaults.
        (_, _), env = _remote_call(
            app, hash_, "list_feed", [devalue.UNDEFINED, devalue.UNDEFINED]
        )
        assert env["type"] == "result"
        page = devalue.parse(env["result"])
        assert len(page["items"]) == 5
        assert page["next_cursor"] is None

        # Garbage cursor fails cleanly, not with a 500.
        (_, _), env = _remote_call(app, hash_, "list_feed", ["not a cursor", 2])
        assert env["type"] == "error"
        assert env["status"] == 400
        assert env["error"] == "bad_cursor"
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_list_feed_types_survive_codegen(paginated_blog: Path):
    for _k in list(sys.modules):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=paginated_blog).build(dev=False)

    dts = (paginated_blog / "dist" / "client" / "_remote" / "feed.d.ts").read_text()
    assert "export interface FeedPage {" in dts
    assert "items: Entry[];" in dts
    assert "next_cursor: string | null;" in dts
    assert (
        "export function list_feed(cursor?: string | null, limit?: number): "
        "Promise<FeedPage>;" in dts
    )
