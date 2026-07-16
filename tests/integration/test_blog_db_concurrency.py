"""Regression test for issue #40: app/data/db.py's get_db() handed every
thread the same sqlite3.Connection, which corrupts cursor state under real
concurrent access (granian, or fymo's own threaded dev server under load).
Reported symptoms were IndexError from fetchall and rows with fields spliced
from two different posts.
"""
import threading
from pathlib import Path

from tests.integration._seed_helpers import seed_test_post

THREADS = 40
ITERATIONS = 100

POSTS = [
    {
        "slug": f"post-{i}",
        "title": f"Title {i}",
        "summary": f"Summary {i}",
        "tags": f"tag-{i}",
    }
    for i in range(8)
]


def test_concurrent_fetchall_does_not_corrupt_rows(blog_app: Path):
    import sys
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    from app.data.db import get_db

    for post in POSTS:
        seed_test_post(
            post["slug"], title=post["title"], summary=post["summary"], tags=post["tags"]
        )
    expected = {p["slug"]: p for p in POSTS}

    errors: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(THREADS)

    def worker() -> None:
        start.wait()
        for _ in range(ITERATIONS):
            try:
                rows = get_db().fetchall(
                    "SELECT slug, title, summary, tags FROM posts ORDER BY slug"
                )
            except Exception as exc:
                with lock:
                    errors.append(f"exception: {exc!r}")
                continue
            for row in rows:
                want = expected.get(row["slug"])
                if want is None:
                    continue
                if (
                    row["title"] != want["title"]
                    or row["summary"] != want["summary"]
                    or row["tags"] != want["tags"]
                ):
                    with lock:
                        errors.append(f"corrupted row for {row['slug']}: {row}")

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"{len(errors)} concurrency failures (showing up to 5): {errors[:5]}"
