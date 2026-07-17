"""identity_extras population on the NEW identity path (issue #80 phase 3).

Hooks registered via register_identity_extras_hook() used to fire only from
the legacy current_user() walk. The generated app/auth/extras.py needs them
to fire when the @identify chain resolves a uid, receiving that uid as the
hook subject, so current_extras() can offer a typed replacement for the
removed current_user() accessor.
"""
import pytest

from fymo.auth import (
    Identity,
    identify,
    identity_extras,
    register_identity_extras_hook,
)
from fymo.auth.context import reset_identity_extras_hooks
from fymo.auth.identity import current_uid, reset_identity_resolvers
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _clean():
    set_secret(b"x" * 32)
    reset_identity_resolvers()
    reset_identity_extras_hooks()
    yield
    reset_identity_resolvers()
    reset_identity_extras_hooks()


def _scope(environ=None):
    return request_scope(uid="u_anon", environ=environ or {})


def test_hook_fires_with_resolved_uid():
    register_identity_extras_hook(lambda uid: {"seen": uid})

    @identify
    def resolver(event):
        return Identity(uid="user-7")

    with _scope():
        assert current_uid() == "user-7"
        assert identity_extras()["seen"] == "user-7"


def test_hook_not_fired_for_anonymous():
    calls = []
    register_identity_extras_hook(lambda uid: calls.append(uid) or {})

    with _scope():
        assert current_uid() is None
        assert dict(identity_extras()) == {}
    assert calls == []


def test_hook_runs_once_per_scope():
    calls = []
    register_identity_extras_hook(lambda uid: calls.append(uid) or {"n": len(calls)})

    @identify
    def resolver(event):
        return Identity(uid="u1")

    with _scope():
        current_uid()
        current_uid()
        assert identity_extras()["n"] == 1
    assert calls == ["u1"]


def test_extras_empty_before_resolution():
    register_identity_extras_hook(lambda uid: {"seen": uid})

    @identify
    def resolver(event):
        return Identity(uid="u1")

    with _scope():
        assert dict(identity_extras()) == {}
        current_uid()
        assert identity_extras()["seen"] == "u1"


def test_no_hooks_registered_is_fine():
    @identify
    def resolver(event):
        return Identity(uid="u1")

    with _scope():
        assert current_uid() == "u1"
        assert dict(identity_extras()) == {}
