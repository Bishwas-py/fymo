"""SqliteUserStore CRUD."""
import sqlite3
from pathlib import Path
import pytest

from fymo.auth.store import EmailAlreadyExists, SqliteUserStore


@pytest.fixture
def store(tmp_path: Path) -> SqliteUserStore:
    return SqliteUserStore(project_root=tmp_path)


def test_create_and_get_by_id(store):
    u = store.create("alice@example.com", "scrypt$hash")
    assert u.id > 0
    assert u.email == "alice@example.com"
    assert u.password_hash == "scrypt$hash"
    assert u.email_verified is False
    assert u.created_at

    fetched = store.get_by_id(u.id)
    assert fetched is not None
    assert fetched.email == u.email


def test_get_by_email_case_insensitive(store):
    store.create("Bob@Example.com", None)
    assert store.get_by_email("bob@example.com") is not None
    assert store.get_by_email("BOB@EXAMPLE.COM") is not None


def test_get_by_email_missing_returns_none(store):
    assert store.get_by_email("nobody@nowhere.com") is None


def test_duplicate_email_raises(store):
    store.create("dup@example.com", "h")
    with pytest.raises(EmailAlreadyExists):
        store.create("dup@example.com", "h")


def test_duplicate_email_case_insensitive(store):
    store.create("UPPER@example.com", "h")
    with pytest.raises(EmailAlreadyExists):
        store.create("upper@example.com", "h")


def test_set_password_hash(store):
    u = store.create("p@p.com", None)
    assert u.password_hash is None
    store.set_password_hash(u.id, "scrypt$new")
    again = store.get_by_id(u.id)
    assert again.password_hash == "scrypt$new"


def test_claim_fymo_uid_is_idempotent(store):
    u = store.create("c@c.com", "h")
    assert u.fymo_uid is None
    store.claim_fymo_uid(u.id, "u_first")
    assert store.get_by_id(u.id).fymo_uid == "u_first"
    # Second claim is a no-op because column is now non-NULL
    store.claim_fymo_uid(u.id, "u_second")
    assert store.get_by_id(u.id).fymo_uid == "u_first"


def test_db_persists_across_store_instances(store, tmp_path: Path):
    u = store.create("persist@me.com", "h")
    store2 = SqliteUserStore(project_root=tmp_path)
    assert store2.get_by_id(u.id) is not None


def test_new_user_starts_at_epoch_one(store):
    u = store.create("epoch@x.com", "h")
    assert u.session_epoch == 1
    assert store.get_by_id(u.id).session_epoch == 1


def test_bump_session_epoch_increments(store):
    u = store.create("bump@x.com", "h")
    store.bump_session_epoch(u.id)
    assert store.get_by_id(u.id).session_epoch == 2
    store.bump_session_epoch(u.id)
    assert store.get_by_id(u.id).session_epoch == 3


def test_set_password_hash_bumps_epoch(store):
    u = store.create("pw@x.com", "h")
    assert u.session_epoch == 1
    store.set_password_hash(u.id, "scrypt$new")
    assert store.get_by_id(u.id).session_epoch == 2


def test_migrates_db_created_before_session_epoch_column(tmp_path: Path):
    """A DB created before the column existed must gain it on open, defaulting
    existing rows to epoch 1 rather than erroring."""
    db_path = tmp_path / "app" / "data" / "auth.db"
    db_path.parent.mkdir(parents=True)
    # Old schema: fymo_users with NO session_epoch column.
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(
        "CREATE TABLE fymo_users ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " email TEXT NOT NULL UNIQUE COLLATE NOCASE,"
        " password_hash TEXT, email_verified INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL, fymo_uid TEXT);"
        "INSERT INTO fymo_users (email, password_hash, created_at)"
        " VALUES ('legacy@x.com', 'h', '2026-01-01T00:00:00+00:00');"
    )
    legacy.commit()
    legacy.close()

    store = SqliteUserStore(project_root=tmp_path)
    user = store.get_by_email("legacy@x.com")
    assert user is not None
    assert user.session_epoch == 1
    # And the revocation path works on the migrated row.
    store.bump_session_epoch(user.id)
    assert store.get_by_id(user.id).session_epoch == 2
