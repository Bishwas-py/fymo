"""Unit tests for fymo.remote.rate_limit's @rate_limit marker decorator.

The decorator stamps configuration on the function object (the same
marker-attribute pattern as @remote's __fymo_remote__ and @require_auth's
__fymo_require_auth__) so the router can enforce a per-function budget at
dispatch time. The marker must survive functools.wraps stacking in any
decorator order, mirroring tests/auth/test_context.py.
"""
import pytest

from fymo.auth.context import require_auth
from fymo.remote.decorators import remote
from fymo.remote.rate_limit import rate_limit


def test_rate_limit_stamps_marker_attribute():
    @rate_limit(per_minute=3)
    def expensive() -> str:
        return "x"

    rule = getattr(expensive, "__fymo_rate_limit__", None)
    assert rule is not None
    assert rule.per_minute == 3
    assert rule.scope == "ip"


def test_explicit_scope_is_stored():
    @rate_limit(per_minute=5, scope="user")
    def expensive() -> str:
        return "x"

    rule = expensive.__fymo_rate_limit__
    assert rule.per_minute == 5
    assert rule.scope == "user"


def test_undecorated_function_has_no_marker():
    def plain() -> str:
        return "x"

    assert getattr(plain, "__fymo_rate_limit__", None) is None


def test_decorator_returns_function_unchanged():
    """No wrapper: like @remote, it only stamps and hands the same object back,
    so signature reflection and identity-keyed caches are unaffected."""
    def expensive() -> str:
        return "x"

    assert rate_limit(per_minute=3)(expensive) is expensive


def test_invalid_scope_raises_value_error():
    with pytest.raises(ValueError, match="scope"):
        @rate_limit(per_minute=3, scope="galaxy")
        def expensive() -> str:
            return "x"


def test_per_minute_below_one_raises_value_error():
    with pytest.raises(ValueError, match="per_minute"):
        @rate_limit(per_minute=0)
        def expensive() -> str:
            return "x"


# ---------------- stacking orders ----------------


def test_marker_survives_remote_above_rate_limit():
    @remote
    @rate_limit(per_minute=3)
    def expensive() -> str:
        return "x"

    assert expensive.__fymo_rate_limit__.per_minute == 3
    assert getattr(expensive, "__fymo_remote__", False) is True


def test_marker_survives_rate_limit_above_remote():
    @rate_limit(per_minute=3)
    @remote
    def expensive() -> str:
        return "x"

    assert expensive.__fymo_rate_limit__.per_minute == 3
    assert getattr(expensive, "__fymo_remote__", False) is True


def test_marker_survives_require_auth_above_rate_limit():
    """@require_auth wraps with functools.wraps, which copies the inner
    function's __dict__ (carrying __fymo_rate_limit__) onto the wrapper."""
    @require_auth
    @rate_limit(per_minute=3, scope="user")
    def expensive() -> str:
        return "x"

    assert expensive.__fymo_rate_limit__.scope == "user"
    assert getattr(expensive, "__fymo_require_auth__", False) is True


def test_marker_survives_rate_limit_above_require_auth():
    @rate_limit(per_minute=3, scope="user")
    @require_auth
    def expensive() -> str:
        return "x"

    assert expensive.__fymo_rate_limit__.scope == "user"
    assert getattr(expensive, "__fymo_require_auth__", False) is True


def test_all_three_markers_survive_full_stack():
    @remote
    @require_auth
    @rate_limit(per_minute=3, scope="user")
    def expensive() -> str:
        return "x"

    assert expensive.__fymo_rate_limit__.per_minute == 3
    assert getattr(expensive, "__fymo_remote__", False) is True
    assert getattr(expensive, "__fymo_require_auth__", False) is True


def test_rate_limit_exported_from_fymo_remote():
    import fymo.remote

    assert fymo.remote.rate_limit is rate_limit
    assert issubclass(fymo.remote.RateLimited, fymo.remote.RemoteError)
