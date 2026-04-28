"""Remote functions for the blog: reads + comment/reaction mutations."""
from datetime import datetime, timezone
from typing import TypedDict, Literal
from pydantic import BaseModel, Field

from fymo.remote import current_uid, NotFound
from app.lib.db import get_db


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


class NewComment(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=1000)


def get_posts() -> list[PostSummary]:
    return get_db().fetchall(
        "SELECT slug, title, summary, tags, published_at FROM posts ORDER BY published_at DESC"
    )


def get_post(slug: str) -> Post:
    row = get_db().fetchone(
        "SELECT slug, title, summary, content_html, tags, published_at FROM posts WHERE slug = ?",
        [slug],
    )
    if not row:
        raise NotFound(f"post '{slug}' not found")
    return row


def get_comments(slug: str) -> list[Comment]:
    return get_db().fetchall(
        "SELECT id, name, body, created_at FROM comments WHERE post_slug = ? ORDER BY created_at DESC",
        [slug],
    )


def create_comment(slug: str, input: NewComment) -> Comment:
    uid = current_uid()
    cid = get_db().execute(
        "INSERT INTO comments (post_slug, uid, name, body, created_at) VALUES (?, ?, ?, ?, ?)",
        [slug, uid, input.name, input.body, datetime.now(timezone.utc).isoformat()],
    )
    return get_db().fetchone(
        "SELECT id, name, body, created_at FROM comments WHERE id = ?", [cid]
    )


def get_reactions(slug: str) -> ReactionCounts:
    rows = get_db().fetchall(
        "SELECT kind, COUNT(*) AS n FROM reactions WHERE post_slug = ? GROUP BY kind",
        [slug],
    )
    counts: ReactionCounts = {"clap": 0, "fire": 0, "heart": 0, "mind": 0}
    for r in rows:
        counts[r["kind"]] = r["n"]
    return counts


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
    return get_reactions(slug)
