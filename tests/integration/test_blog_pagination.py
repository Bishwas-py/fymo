"""End-to-end: the paginated list_posts remote function through real dispatch."""
import base64
import io
import json
import sys
from pathlib import Path
import pytest

from fymo.remote import devalue


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


@pytest.mark.usefixtures("node_available")
def test_list_posts_pages_through_to_the_end(blog_app: Path):
    for _k in list(sys.modules):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]

    from fymo.build.pipeline import BuildPipeline
    from tests.integration._seed_helpers import seed_test_post

    # Five posts: three distinct dates plus two sharing one, so the
    # (published_at, slug) tiebreak actually gets exercised.
    seed_test_post("post-e", published_at="2026-01-05T00:00:00Z")
    seed_test_post("post-d", published_at="2026-01-04T00:00:00Z")
    seed_test_post("post-c2", published_at="2026-01-03T00:00:00Z")
    seed_test_post("post-c1", published_at="2026-01-03T00:00:00Z")
    seed_test_post("post-a", published_at="2026-01-01T00:00:00Z")

    BuildPipeline(project_root=blog_app).build(dev=False)
    manifest = json.loads((blog_app / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["posts"]["hash"]

    from fymo import create_app
    app = create_app(blog_app)
    try:
        # Page 1: no cursor.
        (status, _), env = _remote_call(app, hash_, "list_posts", [None, 2])
        assert status.startswith("200")
        assert env["type"] == "result"
        page1 = devalue.parse(env["result"])
        assert [p["slug"] for p in page1["items"]] == ["post-e", "post-d"]
        assert page1["next_cursor"]

        # Page 2: same-date posts ordered by slug DESC.
        (_, _), env = _remote_call(app, hash_, "list_posts", [page1["next_cursor"], 2])
        page2 = devalue.parse(env["result"])
        assert [p["slug"] for p in page2["items"]] == ["post-c2", "post-c1"]
        assert page2["next_cursor"]

        # Page 3: last row, next_cursor null.
        (_, _), env = _remote_call(app, hash_, "list_posts", [page2["next_cursor"], 2])
        page3 = devalue.parse(env["result"])
        assert [p["slug"] for p in page3["items"]] == ["post-a"]
        assert page3["next_cursor"] is None

        # The generated client sends every positional slot; an argless call
        # arrives as [undefined, undefined] and must use the defaults.
        (_, _), env = _remote_call(
            app, hash_, "list_posts", [devalue.UNDEFINED, devalue.UNDEFINED]
        )
        assert env["type"] == "result"
        page = devalue.parse(env["result"])
        assert len(page["items"]) == 5
        assert page["next_cursor"] is None

        # Garbage cursor fails cleanly, not with a 500.
        (_, _), env = _remote_call(app, hash_, "list_posts", ["not a cursor", 2])
        assert env["type"] == "error"
        assert env["status"] == 400
        assert env["error"] == "bad_cursor"
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_list_posts_types_survive_codegen(blog_app: Path):
    for _k in list(sys.modules):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    dts = (blog_app / "dist" / "client" / "_remote" / "posts.d.ts").read_text()
    assert "export interface PostsPage {" in dts
    assert "items: PostSummary[];" in dts
    assert "next_cursor: string | null;" in dts
    assert (
        "export function list_posts(cursor?: string | null, limit?: number): "
        "Promise<PostsPage>;" in dts
    )
