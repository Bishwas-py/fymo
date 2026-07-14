"""Broadcast channels for the blog: live comment/reaction activity on a
post, pushed to anyone reading that post's page.

Reference example for the app/broadcasts/*.py convention: the function
signature is the subscribe args, the return annotation is the payload
`publish()` is checked against in dev mode, and the body is the
subscribe-time authorization guard, run for real on every SSE subscribe
(see fymo/broadcast/sse.py's _run_guard).
"""
from typing import Literal, NotRequired, TypedDict

from app.data.db import get_db
from app.remote.posts import Comment, ReactionCounts
from fymo.remote import NotFound


class PostActivity(TypedDict):
    kind: Literal["comment_added", "reaction_updated"]
    comment: NotRequired[Comment]
    reactions: NotRequired[ReactionCounts]


def post_activity(slug: str) -> PostActivity:
    # Deny subscribing to a post that isn't there (typo'd slug, deleted
    # post) rather than silently opening a channel nothing will ever
    # publish to. Everything else is open: posts are public, so anyone
    # reading a post may watch its comment/reaction activity live, same
    # visibility as get_comments()/get_reactions() already have.
    if not get_db().fetchone("SELECT 1 FROM posts WHERE slug = ?", [slug]):
        raise NotFound(f"post '{slug}' not found")
