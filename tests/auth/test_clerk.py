"""Hosted-token provider (Clerk): resolve identity by verifying a request token."""
from pathlib import Path

import pytest

from fymo.auth import context as auth_context
from fymo.auth.context import current_user, register_session_resolver, reset_session_resolvers
from fymo.auth.store import SqliteUserStore
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture
def wired(tmp_path: Path):
    set_secret(b"x" * 32)
    store = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(store)
    yield store
    reset_session_resolvers()


def _clerk(verify):
    from fymo.auth.providers.clerk import ClerkProvider
    return ClerkProvider(issuer="https://x.clerk.accounts.dev", jwks_url="https://x/jwks", verify=verify)


def test_resolves_and_provisions_user_from_verified_token(wired):
    store = wired
    prov = _clerk(
        lambda tok: {"sub": "clerk-1", "email": "c@example.com", "email_verified": True}
        if tok == "good" else None
    )
    reset_session_resolvers()
    register_session_resolver(prov.resolve_session)

    with request_scope(uid="u", environ={"HTTP_AUTHORIZATION": "Bearer good"}):
        user = current_user()
    assert user is not None
    assert user.email == "c@example.com"
    # Provisioned + linked under the clerk provider.
    assert store.get_by_identity("clerk", "clerk-1").id == user.id


def test_rejects_invalid_token(wired):
    prov = _clerk(lambda tok: None)
    reset_session_resolvers()
    register_session_resolver(prov.resolve_session)
    with request_scope(uid="u", environ={"HTTP_AUTHORIZATION": "Bearer bad"}):
        assert current_user() is None


def test_no_token_is_no_session(wired):
    prov = _clerk(lambda tok: {"sub": "x"})
    assert prov.resolve_session({"cookies": {}, "headers": {}}) is None
