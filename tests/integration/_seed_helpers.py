"""Shared test-only post fixture for blog_app integration tests.

Replaces the old markdown-file seeder (app/data/seeder.py, removed along
with app/posts/*.md -- the example no longer ships canned demo content).
Tests that need a real row in the `posts` table call seed_test_post()
directly instead, after the test's blog_app copy is on sys.path.
"""


def seed_test_post(slug: str = "welcome-to-fymo", **overrides) -> None:
    """Insert one post row directly via app.data.db, bypassing markdown
    parsing entirely. Default fields match the old seeded "welcome-to-fymo"
    post closely enough that existing assertions (slug, title-ish content)
    keep working unchanged; pass overrides for anything a specific test
    needs to differ."""
    from app.data.db import get_db

    row = {
        "slug": slug,
        "title": "Welcome to Fymo",
        "summary": "A test post for integration tests.",
        "content_html": "<p>Test post content.</p>",
        "tags": "test",
        "published_at": "2026-01-01T00:00:00Z",
    }
    row.update(overrides)

    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO posts (slug, title, summary, content_html, tags, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [row["slug"], row["title"], row["summary"], row["content_html"], row["tags"], row["published_at"]],
    )
