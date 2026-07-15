"""Unit tests for fymo.auth.context's require_auth marker attribute.

Issue #29's build-time check needs a way to tell whether a given app/remote
function is guarded by @require_auth without re-deriving the answer from
behavior (calling it and checking for a 401). The marker mirrors the
__fymo_remote__ pattern fymo/remote/decorators.py already uses for @remote.
"""
from fymo.auth.context import require_auth
from fymo.remote.decorators import remote


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
