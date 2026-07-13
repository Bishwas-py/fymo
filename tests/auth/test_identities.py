"""External-identity linking on the UserStore (OAuth account model)."""
from pathlib import Path

import pytest

from fymo.auth.store import SqliteUserStore


@pytest.fixture
def store(tmp_path: Path) -> SqliteUserStore:
    return SqliteUserStore(project_root=tmp_path)


def test_link_and_get_by_identity(store):
    user = store.create("g@example.com", None)
    assert store.get_by_identity("google", "sub-123") is None

    store.link_identity(user.id, "google", "sub-123", "g@example.com")
    got = store.get_by_identity("google", "sub-123")
    assert got is not None
    assert got.id == user.id
    assert got.email == "g@example.com"


def test_link_identity_is_idempotent(store):
    user = store.create("h@example.com", None)
    store.link_identity(user.id, "google", "sub-9", "h@example.com")
    # Linking the same (provider, sub) again must not raise or duplicate.
    store.link_identity(user.id, "google", "sub-9", "h@example.com")
    assert store.get_by_identity("google", "sub-9").id == user.id


def test_identity_is_scoped_by_provider(store):
    a = store.create("a@example.com", None)
    b = store.create("b@example.com", None)
    store.link_identity(a.id, "google", "shared-sub", "a@example.com")
    store.link_identity(b.id, "github", "shared-sub", "b@example.com")
    assert store.get_by_identity("google", "shared-sub").id == a.id
    assert store.get_by_identity("github", "shared-sub").id == b.id
