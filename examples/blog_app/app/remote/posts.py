"""Remote functions for the blog: reads + comment/reaction mutations."""
import logging
from datetime import datetime, timezone
from typing import TypedDict, Literal
from pydantic import BaseModel, Field

from fymo.remote import current_uid, NotFound, remote, decode_cursor, paginate
from fymo.auth import require_auth, current_user
from app.data.db import get_db

logger = logging.getLogger("blog_app")


class Post(TypedDict):
    slug: str
    title: str
    summary: str
    content_html: str
    tags: str
    published_at: str


class PostSummary(TypedDict):
    slug: str
    title: str
    summary: str
    tags: str
    published_at: str


class Comment(TypedDict):
    id: int
    name: str
    body: str
    created_at: str


ReactionKind = Literal["clap", "fire", "heart", "mind"]


class ReactionCounts(TypedDict):
    clap: int
    fire: int
    heart: int
    mind: int


class PostsPage(TypedDict):
    items: list[PostSummary]
    next_cursor: str | None


class NewComment(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


@remote
def get_posts() -> list[PostSummary]:
    return get_db().fetchall(
        "SELECT slug, title, summary, tags, published_at FROM posts ORDER BY published_at DESC"
    )


@remote
def list_posts(cursor: str | None = None, limit: int = 20) -> PostsPage:
    # Cursor pagination over (published_at, slug): published_at alone isn't
    # unique, so slug breaks ties. Fetch one row past `limit`; paginate()
    # turns that extra row into next_cursor (null on the last page).
    limit = max(1, min(limit, 50))
    fields = "slug, title, summary, tags, published_at"
    if cursor:
        published_at, slug = decode_cursor(cursor, expect=2)
        rows = get_db().fetchall(
            f"SELECT {fields} FROM posts WHERE (published_at, slug) < (?, ?) "
            "ORDER BY published_at DESC, slug DESC LIMIT ?",
            [published_at, slug, limit + 1],
        )
    else:
        rows = get_db().fetchall(
            f"SELECT {fields} FROM posts ORDER BY published_at DESC, slug DESC LIMIT ?",
            [limit + 1],
        )
    return paginate(rows, limit, key=lambda p: (p["published_at"], p["slug"]))


@remote
def get_post(slug: str) -> Post:
    row = get_db().fetchone(
        "SELECT slug, title, summary, content_html, tags, published_at FROM posts WHERE slug = ?",
        [slug],
    )
    if not row:
        raise NotFound(f"post '{slug}' not found")
    return row


def _publish_activity(slug: str, kind: str, **payload) -> None:
    # Fire-and-forget: a subscriber missing this event isn't broken, they
    # just fall back to whatever polling/refresh already covers the page,
    # so a broadcast failure must never fail the mutation that triggered it.
    try:
        from fymo.broadcast import publish
        publish("post_activity", slug=slug, data={"kind": kind, **payload})
    except Exception:
        logger.warning("post_activity broadcast failed for %s", slug, exc_info=True)


@remote
def get_comments(slug: str) -> list[Comment]:
    return get_db().fetchall(
        "SELECT id, name, body, created_at FROM comments WHERE post_slug = ? ORDER BY created_at DESC",
        [slug],
    )


@remote
@require_auth
def create_comment(slug: str, input: NewComment) -> Comment:
    # Author comes from the authenticated session, never client input. Display
    # the email's local part as a handle rather than the full address.
    author = current_user().email.split("@")[0]
    uid = current_uid()
    cid = get_db().execute(
        "INSERT INTO comments (post_slug, uid, name, body, created_at) VALUES (?, ?, ?, ?, ?)",
        [slug, uid, author, input.body, datetime.now(timezone.utc).isoformat()],
    )
    comment = get_db().fetchone(
        "SELECT id, name, body, created_at FROM comments WHERE id = ?", [cid]
    )
    _publish_activity(slug, "comment_added", comment=comment)
    return comment


@remote
def get_reactions(slug: str) -> ReactionCounts:
    rows = get_db().fetchall(
        "SELECT kind, COUNT(*) AS n FROM reactions WHERE post_slug = ? GROUP BY kind",
        [slug],
    )
    counts: ReactionCounts = {"clap": 0, "fire": 0, "heart": 0, "mind": 0}
    for r in rows:
        counts[r["kind"]] = r["n"]
    return counts


@remote
def toggle_reaction(slug: str, kind: ReactionKind) -> ReactionCounts:
    uid = current_uid()
    db = get_db()
    existing = db.fetchone(
        "SELECT 1 FROM reactions WHERE post_slug = ? AND uid = ? AND kind = ?",
        [slug, uid, kind],
    )
    if existing:
        db.execute(
            "DELETE FROM reactions WHERE post_slug = ? AND uid = ? AND kind = ?",
            [slug, uid, kind],
        )
    else:
        db.execute(
            "INSERT INTO reactions (post_slug, uid, kind) VALUES (?, ?, ?)",
            [slug, uid, kind],
        )
    reactions = get_reactions(slug)
    _publish_activity(slug, "reaction_updated", reactions=reactions)
    return reactions
