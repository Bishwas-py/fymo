"""Unit tests for fymo.auth.context's @require_auth decorator.

Behavior (issue #80): the guard consults current_uid(), the @identify
resolver chain, and raises AuthRequired (401, code "unauthenticated")
when no resolver recognizes the request.

Marker attribute (issue #29): build-time checks need a way to tell
whether a given app/remote function is guarded by @require_auth without
re-deriving the answer from behavior (calling it and checking for a 401).
The marker mirrors the __fymo_remote__ pattern
fymo/remote/decorators.py already uses for @remote.
"""
import pytest

from fymo.auth import Identity, identify
from fymo.auth.context import AuthRequired, require_auth
from fymo.auth.identity import reset_identity_resolvers
from fymo.remote.context import request_scope
from fymo.remote.decorators import remote


@pytest.fixture(autouse=True)
def _clean_resolvers():
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()


# --------------- behavior: the new identity chain ---------------


def test_require_auth_passes_when_identify_chain_resolves():
    @identify
    def by_header(event):
        uid = event.headers.get("x-user")
        return Identity(uid=uid) if uid else None

    @require_auth
    def guarded() -> str:
        return "ok"

    with request_scope(uid="u_anon", environ={"HTTP_X_USER": "u_alice"}):
        assert guarded() == "ok"


def test_require_auth_raises_when_no_resolver_matches():
    @identify
    def never(event):
        return None

    @require_auth
    def guarded() -> str:
        return "ok"

    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(AuthRequired) as excinfo:
            guarded()
    assert excinfo.value.status == 401
    assert excinfo.value.code == "unauthenticated"


def test_require_auth_raises_with_zero_resolvers_registered():
    @require_auth
    def guarded() -> str:
        return "ok"

    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(AuthRequired):
            guarded()


def test_require_auth_never_calls_the_function_when_anonymous():
    calls = []

    @require_auth
    def guarded() -> str:
        calls.append(1)
        return "ok"

    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(AuthRequired):
            guarded()
    assert calls == []


# --------------- marker attribute ---------------


def test_require_auth_stamps_marker_attribute():
    @require_auth
    def guarded() -> str:
        return "ok"

    assert getattr(guarded, "__fymo_require_auth__", False) is True


def test_plain_function_has_no_marker():
    def unguarded() -> str:
        return "ok"

    assert getattr(unguarded, "__fymo_require_auth__", False) is False


def test_marker_survives_remote_decorator_applied_above_require_auth():
    """@remote sits outside, @require_auth inside: remote() stamps and
    returns the require_auth wrapper unchanged, so the marker must still
    be there."""
    @remote
    @require_auth
    def guarded() -> str:
        return "ok"

    assert getattr(guarded, "__fymo_require_auth__", False) is True
    assert getattr(guarded, "__fymo_remote__", False) is True


def test_marker_survives_remote_decorator_applied_below_require_auth():
    """@require_auth sits outside, @remote inside: functools.wraps copies
    the inner function's __dict__ (which already has __fymo_remote__ from
    @remote) onto the wrapper, so both markers must survive here too."""
    @require_auth
    @remote
    def guarded() -> str:
        return "ok"

    assert getattr(guarded, "__fymo_require_auth__", False) is True
    assert getattr(guarded, "__fymo_remote__", False) is True
