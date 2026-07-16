"""UserStore Protocol conformance battery, run identically against every
shipped backend.

SqliteUserStore always runs. PostgresUserStore runs only when
TEST_DATABASE_URL points at a reachable Postgres instance (the same opt-in
the procrastinate and postgres-broadcast tests use); otherwise its half of
the matrix is skipped with that reason. The Postgres half drops and
recreates the fymo_ auth tables per test, so point TEST_DATABASE_URL at a
scratch database, never a real one.
"""
import os
import time
from pathlib import Path

import pytest

from fymo.auth.store import EmailAlreadyExists, SqliteUserStore, User, UserStore
from fymo.auth.verify_token import make_reset_token, make_verify_token
from fymo.remote import identity
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _wire_secret():
    previous = identity._secret
    set_secret(b"x" * 32)
    yield
    identity._secret = previous


@pytest.fixture(params=["sqlite", "postgres"])
def store_factory(request, tmp_path: Path, monkeypatch):
    """Callable returning a fresh store instance over the same backend state.

    Most tests use the derived `store` fixture; the persistence test calls
    this twice to prove data survives an instance swap.
    """
    created = []
    if request.param == "sqlite":
        def make():
            s = SqliteUserStore(tmp_path)
            created.append(s)
            return s
        yield make
    else:
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            pytest.skip("needs TEST_DATABASE_URL pointing at a real Postgres instance")
        monkeypatch.setenv("DATABASE_URL", url)
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                "DROP TABLE IF EXISTS fymo_user_oauth_identities, fymo_users"
            )
        from fymo.auth.postgres_store import PostgresUserStore

        def make():
            s = PostgresUserStore(tmp_path)
            created.append(s)
            return s
        yield make
    for s in created:
        close = getattr(s, "close", None)
        if close is not None:
            close()


@pytest.fixture
def store(store_factory):
    return store_factory()


# Protocol shape

def test_satisfies_userstore_protocol(store):
    assert isinstance(store, UserStore)


# create / get_by_id / get_by_email

def test_create_and_get_by_id(store):
    u = store.create("alice@example.com", "scrypt$hash")
    assert isinstance(u, User)
    assert u.id > 0
    assert u.email == "alice@example.com"
    assert u.password_hash == "scrypt$hash"
    assert u.email_verified is False
    assert u.created_at
    assert u.fymo_uid is None
    assert u.session_epoch == 1

    fetched = store.get_by_id(u.id)
    assert fetched is not None
    assert fetched.id == u.id
    assert fetched.email == u.email
    assert fetched.password_hash == u.password_hash
    assert fetched.email_verified is False
    assert fetched.created_at == u.created_at
    assert fetched.session_epoch == 1


def test_create_allows_null_password_hash(store):
    u = store.create("oauth-only@example.com", None)
    assert u.password_hash is None
    assert store.get_by_id(u.id).password_hash is None


def test_get_by_id_missing_returns_none(store):
    assert store.get_by_id(999999) is None


def test_get_by_email_missing_returns_none(store):
    assert store.get_by_email("nobody@nowhere.com") is None


def test_get_by_email_is_case_insensitive(store):
    store.create("Bob@Example.com", None)
    assert store.get_by_email("bob@example.com") is not None
    assert store.get_by_email("BOB@EXAMPLE.COM") is not None


def test_duplicate_email_raises(store):
    store.create("dup@example.com", "h")
    with pytest.raises(EmailAlreadyExists):
        store.create("dup@example.com", "h")


def test_duplicate_email_case_insensitive(store):
    store.create("UPPER@example.com", "h")
    with pytest.raises(EmailAlreadyExists):
        store.create("upper@example.com", "h")


def test_store_still_usable_after_duplicate_email(store):
    """The failed INSERT must not poison later calls (a Postgres backend
    that forgets to roll back would fail every statement after the first
    unique violation)."""
    store.create("first@example.com", "h")
    with pytest.raises(EmailAlreadyExists):
        store.create("first@example.com", "h")
    u = store.create("second@example.com", "h")
    assert store.get_by_id(u.id) is not None
    assert store.get_by_email("first@example.com") is not None


def test_persists_across_store_instances(store_factory):
    first = store_factory()
    u = first.create("persist@me.com", "h")
    second = store_factory()
    again = second.get_by_id(u.id)
    assert again is not None
    assert again.email == "persist@me.com"


# password / session epoch

def test_set_password_hash_updates_hash(store):
    u = store.create("p@p.com", None)
    store.set_password_hash(u.id, "scrypt$new")
    assert store.get_by_id(u.id).password_hash == "scrypt$new"


def test_set_password_hash_bumps_epoch(store):
    u = store.create("pw@x.com", "h")
    assert u.session_epoch == 1
    store.set_password_hash(u.id, "scrypt$new")
    assert store.get_by_id(u.id).session_epoch == 2


def test_bump_session_epoch_increments(store):
    u = store.create("bump@x.com", "h")
    store.bump_session_epoch(u.id)
    assert store.get_by_id(u.id).session_epoch == 2
    store.bump_session_epoch(u.id)
    assert store.get_by_id(u.id).session_epoch == 3


# fymo_uid claim

def test_claim_fymo_uid_sets_once(store):
    u = store.create("c@c.com", "h")
    assert u.fymo_uid is None
    store.claim_fymo_uid(u.id, "u_first")
    assert store.get_by_id(u.id).fymo_uid == "u_first"


def test_claim_fymo_uid_is_idempotent(store):
    u = store.create("c2@c.com", "h")
    store.claim_fymo_uid(u.id, "u_first")
    store.claim_fymo_uid(u.id, "u_second")
    assert store.get_by_id(u.id).fymo_uid == "u_first"


# external identities

def test_link_identity_and_get_by_identity_roundtrip(store):
    u = store.create("id@x.com", None)
    store.link_identity(u.id, "google", "sub-123", "id@x.com")
    found = store.get_by_identity("google", "sub-123")
    assert found is not None
    assert found.id == u.id


def test_get_by_identity_unknown_returns_none(store):
    assert store.get_by_identity("google", "no-such-sub") is None


def test_link_identity_first_link_wins(store):
    """Relinking the same (provider, sub) to another user is a no-op."""
    a = store.create("a@x.com", None)
    b = store.create("b@x.com", None)
    store.link_identity(a.id, "github", "sub-1", "a@x.com")
    store.link_identity(b.id, "github", "sub-1", "b@x.com")
    assert store.get_by_identity("github", "sub-1").id == a.id


def test_link_identity_distinct_subs_map_to_distinct_users(store):
    a = store.create("a2@x.com", None)
    b = store.create("b2@x.com", None)
    store.link_identity(a.id, "github", "sub-a", None)
    store.link_identity(b.id, "github", "sub-b", None)
    assert store.get_by_identity("github", "sub-a").id == a.id
    assert store.get_by_identity("github", "sub-b").id == b.id


def test_one_user_can_hold_identities_from_multiple_providers(store):
    u = store.create("multi@x.com", None)
    store.link_identity(u.id, "google", "g-sub", None)
    store.link_identity(u.id, "github", "h-sub", None)
    assert store.get_by_identity("google", "g-sub").id == u.id
    assert store.get_by_identity("github", "h-sub").id == u.id


# email verification tokens

def test_consume_verify_token_marks_verified(store):
    u = store.create("v@x.com", "h")
    token = make_verify_token(u.id)
    store.set_verify_token(u.id, token)
    assert store.consume_verify_token(token) == u.id
    assert store.get_by_id(u.id).email_verified is True


def test_consume_verify_token_is_single_use(store):
    u = store.create("v2@x.com", "h")
    token = make_verify_token(u.id)
    store.set_verify_token(u.id, token)
    assert store.consume_verify_token(token) == u.id
    assert store.consume_verify_token(token) is None


def test_consume_verify_token_garbage_returns_none(store):
    assert store.consume_verify_token("not.a.token") is None


def test_consume_verify_token_never_issued_returns_none(store):
    """Signature-valid token for a user that never had one recorded."""
    u = store.create("v3@x.com", "h")
    assert store.consume_verify_token(make_verify_token(u.id)) is None
    assert store.get_by_id(u.id).email_verified is False


def test_consume_verify_token_unknown_user_returns_none(store):
    assert store.consume_verify_token(make_verify_token(999999)) is None


def test_consume_verify_token_superseded_returns_none(store):
    """A newer set_verify_token invalidates the earlier token."""
    u = store.create("v4@x.com", "h")
    now = int(time.time())
    old = make_verify_token(u.id, issued_at=now - 10)
    new = make_verify_token(u.id, issued_at=now)
    store.set_verify_token(u.id, old)
    store.set_verify_token(u.id, new)
    assert store.consume_verify_token(old) is None
    assert store.consume_verify_token(new) == u.id


# password reset tokens

def test_consume_reset_token_returns_user_id(store):
    u = store.create("r@x.com", "h")
    token = make_reset_token(u.id)
    store.set_reset_token(u.id, token)
    assert store.consume_reset_token(token) == u.id


def test_consume_reset_token_does_not_verify_email(store):
    u = store.create("r2@x.com", "h")
    token = make_reset_token(u.id)
    store.set_reset_token(u.id, token)
    store.consume_reset_token(token)
    assert store.get_by_id(u.id).email_verified is False


def test_consume_reset_token_is_single_use(store):
    u = store.create("r3@x.com", "h")
    token = make_reset_token(u.id)
    store.set_reset_token(u.id, token)
    assert store.consume_reset_token(token) == u.id
    assert store.consume_reset_token(token) is None


def test_consume_reset_token_never_issued_returns_none(store):
    u = store.create("r4@x.com", "h")
    assert store.consume_reset_token(make_reset_token(u.id)) is None


def test_consume_reset_token_superseded_returns_none(store):
    u = store.create("r5@x.com", "h")
    now = int(time.time())
    old = make_reset_token(u.id, issued_at=now - 10)
    new = make_reset_token(u.id, issued_at=now)
    store.set_reset_token(u.id, old)
    store.set_reset_token(u.id, new)
    assert store.consume_reset_token(old) is None
    assert store.consume_reset_token(new) == u.id


def test_concurrent_creates_from_many_threads(store):
    """Both backends must survive parallel writers: SqliteUserStore via its
    connection lock, PostgresUserStore via the connection pool (more threads
    here than the pool's max_size, so waiting is exercised too)."""
    import threading
    errors = []

    def work(i: int) -> None:
        try:
            u = store.create(f"thread{i}@x.com", "h")
            assert store.get_by_id(u.id).email == f"thread{i}@x.com"
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert all(not t.is_alive() for t in threads)


def test_tokens_are_purpose_bound(store):
    """A verify token can never be consumed as a reset token or vice versa,
    even for the same user with both outstanding."""
    u = store.create("cross@x.com", "h")
    verify = make_verify_token(u.id)
    reset = make_reset_token(u.id)
    store.set_verify_token(u.id, verify)
    store.set_reset_token(u.id, reset)
    assert store.consume_reset_token(verify) is None
    assert store.consume_verify_token(reset) is None
    assert store.consume_verify_token(verify) == u.id
    assert store.consume_reset_token(reset) == u.id
