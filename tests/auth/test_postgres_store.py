"""PostgresUserStore behavior outside the shared conformance battery.

Boot-time failure modes need no database and always run: both must raise at
construction with an actionable message, never on the first request. The
migration test needs a real Postgres and is gated on TEST_DATABASE_URL like
the conformance battery.
"""
import os
import sys
from pathlib import Path

import pytest

from fymo.auth.postgres_store import PostgresUserStore
from fymo.auth.store import EmailAlreadyExists, SqliteUserStore


def test_missing_database_url_raises_at_construction(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        PostgresUserStore(tmp_path)


def test_missing_psycopg_names_the_install_command(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
    # A None entry in sys.modules makes `import psycopg` raise ImportError,
    # simulating the extra not being installed.
    monkeypatch.setitem(sys.modules, "psycopg", None)
    with pytest.raises(RuntimeError, match=r"fymo\[postgres\]"):
        PostgresUserStore(tmp_path)


def test_construction_does_not_connect(monkeypatch, tmp_path: Path):
    """The pool opens on first use, like SqliteUserStore's lazy connect;
    an unreachable database must not block boot."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:1/nowhere")
    store = PostgresUserStore(tmp_path)
    assert store._pool is None


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs TEST_DATABASE_URL pointing at a real Postgres instance",
)
def test_migrates_table_created_before_later_columns(monkeypatch, tmp_path: Path):
    """A fymo_users table created before the session_epoch and token columns
    existed must gain them on first connect, defaulting existing rows to
    epoch 1 rather than erroring. Mirror of the SqliteUserStore migration
    test in test_store.py."""
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    import psycopg
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS fymo_user_oauth_identities, fymo_users")
        conn.execute(
            "CREATE TABLE fymo_users ("
            " id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            " email TEXT NOT NULL,"
            " password_hash TEXT,"
            " email_verified BOOLEAN NOT NULL DEFAULT FALSE,"
            " created_at TEXT NOT NULL,"
            " fymo_uid TEXT)"
        )
        conn.execute(
            "INSERT INTO fymo_users (email, password_hash, created_at)"
            " VALUES ('legacy@x.com', 'h', '2026-01-01T00:00:00+00:00')"
        )

    store = PostgresUserStore(tmp_path)
    try:
        user = store.get_by_email("legacy@x.com")
        assert user is not None
        assert user.session_epoch == 1
        store.bump_session_epoch(user.id)
        assert store.get_by_id(user.id).session_epoch == 2
    finally:
        store.close()


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs TEST_DATABASE_URL pointing at a real Postgres instance",
)
def test_non_ascii_email_case_collision_diverges_from_sqlite(monkeypatch, tmp_path: Path):
    """Known, documented divergence (see the module docstring): lower()
    folds per the database locale while SQLite's NOCASE folds ASCII only,
    so these two spellings coexist as distinct users in a SQLite auth.db
    but collide here. Consequence: a SQLite database already holding both
    cannot be imported into this store."""
    sqlite_store = SqliteUserStore(tmp_path)
    sqlite_store.create("É@example.com", "h")
    sqlite_store.create("é@example.com", "h")

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    import psycopg
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS fymo_user_oauth_identities, fymo_users")
    store = PostgresUserStore(tmp_path)
    try:
        store.create("É@example.com", "h")
        with pytest.raises(EmailAlreadyExists):
            store.create("é@example.com", "h")
    finally:
        store.close()


def test_bootstrap_failure_closes_the_pool(monkeypatch, tmp_path: Path):
    """If schema bootstrap raises on the first call (transient outage), the
    freshly built pool must be closed, not leaked with its background
    workers reconnecting forever, and _pool must stay None so the next
    call retries from scratch."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
    store = PostgresUserStore(tmp_path)

    created = []

    class FakePool:
        def __init__(self, *args, **kwargs):
            self.closed = False
            created.append(self)

        def connection(self):
            raise RuntimeError("bootstrap boom")

        def close(self):
            self.closed = True

    class FakePoolModule:
        ConnectionPool = FakePool

    monkeypatch.setattr(store, "_psycopg_pool", FakePoolModule)
    with pytest.raises(RuntimeError, match="bootstrap boom"):
        store.get_by_id(1)
    assert store._pool is None
    assert len(created) == 1
    assert created[0].closed is True
