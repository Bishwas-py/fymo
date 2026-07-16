"""SQLite singleton with schema migration on first connect."""
import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_html TEXT NOT NULL,
    tags TEXT NOT NULL,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_slug TEXT NOT NULL REFERENCES posts(slug),
    uid TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reactions (
    post_slug TEXT NOT NULL REFERENCES posts(slug),
    uid TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('clap', 'fire', 'heart', 'mind')),
    PRIMARY KEY (post_slug, uid, kind)
);
"""


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread: sqlite3 connections aren't safe to share
        # across threads under a threaded server (granian, or fymo's own dev
        # server), so each thread gets its own on first use.
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path))
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            self._local.conn = conn
        return conn

    def fetchone(self, sql: str, params: list[Any] = ()) -> dict | None:
        row = self.connect().execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: list[Any] = ()) -> list[dict]:
        rows = self.connect().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def execute(self, sql: str, params: list[Any] = ()) -> int:
        cur = self.connect().execute(sql, params)
        self.connect().commit()
        return cur.lastrowid


# Module-level instance — initialized lazily by callers
_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        # Resolve project root from this file's location
        project_root = Path(__file__).resolve().parent.parent.parent
        _db = DB(project_root / "app" / "data" / "blog.db")
    return _db
