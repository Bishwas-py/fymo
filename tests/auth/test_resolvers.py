"""current_user() resolves identity through a provider-extensible chain."""
from pathlib import Path

import pytest

from fymo.auth import context as auth_context
from fymo.auth.context import (
    current_user,
    register_session_resolver,
    reset_session_resolvers,
)
from fymo.auth.session import make_session_token
from fymo.auth.store import SqliteUserStore
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture
def store(tmp_path: Path):
    set_secret(b"x" * 32)
    s = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(s)
    yield s
    reset_session_resolvers()


def test_custom_resolver_used_when_no_fymo_session(store):
    """A provider can teach current_user() to resolve identity from a token/header
    the built-in cookie resolver knows nothing about (Axis B)."""
    user = store.create("token@example.com", "hash")
    reset_session_resolvers()
    register_session_resolver(
        lambda event: store.get_by_id(user.id)
        if event.get("headers", {}).get("x-provider-token") == "ok"
        else None
    )
    with request_scope(uid="u_x", environ={"HTTP_X_PROVIDER_TOKEN": "ok"}):
        resolved = current_user()
    assert resolved is not None
    assert resolved.email == "token@example.com"


def test_fymo_session_takes_precedence_over_providers(store):
    """When a request carries both a fymo session and a provider token, the
    built-in cookie resolver wins (deterministic, config order)."""
    alice = store.create("alice@example.com", "hash")
    bob = store.create("bob@example.com", "hash")
    reset_session_resolvers()
    register_session_resolver(lambda event: store.get_by_id(bob.id))  # always "bob"

    token = make_session_token(alice.id, alice.session_epoch)
    with request_scope(
        uid="u_x",
        environ={"HTTP_COOKIE": f"fymo_session={token}", "HTTP_X_PROVIDER_TOKEN": "ok"},
    ):
        resolved = current_user()
    assert resolved.email == "alice@example.com"


def test_no_resolver_matches_returns_none(store):
    reset_session_resolvers()
    with request_scope(uid="u_x", environ={}):
        assert current_user() is None
