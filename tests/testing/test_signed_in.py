"""fymo.testing.signed_in / acting_as: fake authenticated identities for tests.

The new model (issue #80): identity is an opaque uid resolved through the
@identify chain. signed_in registers a test resolver through that chain and
opens a request scope; acting_as swaps the resolved identity mid-block.
"""
import pytest

from fymo.auth import Identity, current_uid, identify, identity_extras
from fymo.auth.identity import (
    registered_identity_resolvers,
    reset_identity_resolvers,
)
from fymo.remote.context import _current_event, request_scope
from fymo.testing import acting_as, signed_in


@pytest.fixture(autouse=True)
def clean_registry():
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()


# --------------- signed_in ---------------


def test_signed_in_yields_identity_with_default_uid():
    with signed_in() as ident:
        assert isinstance(ident, Identity)
        assert ident.uid == "u_test1"


def test_signed_in_default_uid_resolves():
    with signed_in():
        assert current_uid() == "u_test1"


def test_signed_in_custom_uid_resolves():
    with signed_in("u_alice") as ident:
        assert ident.uid == "u_alice"
        assert current_uid() == "u_alice"


def test_signed_in_registers_through_the_identify_chain():
    assert registered_identity_resolvers() == ()
    with signed_in():
        chain = registered_identity_resolvers()
        assert len(chain) == 1
    assert registered_identity_resolvers() == ()


def test_sequential_signed_in_blocks_resolve_their_own_uid():
    # Both blocks register the same module-level resolver; what makes the
    # second block resolve its own uid is that the resolver reads the acting
    # identity from a contextvar set at block entry, never from state
    # captured at registration time.
    with signed_in("u_alice"):
        assert current_uid() == "u_alice"
    with signed_in("u_bob"):
        assert current_uid() == "u_bob"


def test_signed_in_blocks_nest_inner_wins_then_outer_restores():
    with signed_in("u_outer"):
        assert current_uid() == "u_outer"
        with signed_in("u_inner"):
            assert current_uid() == "u_inner"
        assert current_uid() == "u_outer"
    assert registered_identity_resolvers() == ()


def test_signed_in_preserves_preexisting_resolvers():
    def sentinel(event):
        return None

    identify(sentinel)
    with signed_in("u_x"):
        assert current_uid() == "u_x"
    assert registered_identity_resolvers() == (sentinel,)


def test_signed_in_cleans_up_when_body_raises():
    with pytest.raises(ValueError):
        with signed_in():
            raise ValueError("boom")
    assert registered_identity_resolvers() == ()
    assert _current_event.get() is None
    with pytest.raises(RuntimeError):
        current_uid()


def test_anonymous_scope_outside_signed_in_resolves_none():
    with request_scope(uid="u_anon", environ={}):
        assert current_uid() is None


def test_no_resolver_leaks_into_a_later_plain_scope():
    with signed_in("u_alice"):
        assert current_uid() == "u_alice"
    with request_scope(uid="u_anon", environ={}):
        assert current_uid() is None


# --------------- extras ---------------


def test_signed_in_without_extras_has_empty_extras():
    with signed_in():
        assert dict(identity_extras()) == {}


def test_signed_in_extras_flow_through_identity_extras():
    with signed_in("u_admin", extras={"role": "admin", "org": "acme"}):
        assert identity_extras()["role"] == "admin"
        assert identity_extras()["org"] == "acme"


def test_signed_in_extras_are_read_only():
    with signed_in(extras={"role": "admin"}):
        with pytest.raises(TypeError):
            identity_extras()["role"] = "hacker"


def test_signed_in_extras_do_not_leak_into_next_block():
    with signed_in("u_admin", extras={"role": "admin"}):
        pass
    with signed_in("u_plain"):
        assert dict(identity_extras()) == {}


# --------------- acting_as ---------------


def test_acting_as_yields_identity():
    with signed_in():
        with acting_as("u_bob") as ident:
            assert isinstance(ident, Identity)
            assert ident.uid == "u_bob"


def test_acting_as_swaps_and_restores_uid():
    with signed_in("u_alice"):
        assert current_uid() == "u_alice"
        with acting_as("u_bob"):
            assert current_uid() == "u_bob"
        assert current_uid() == "u_alice"


def test_acting_as_overrides_cached_resolution():
    with signed_in("u_alice"):
        # Prime the per-scope resolution cache before swapping.
        assert current_uid() == "u_alice"
        with acting_as("u_bob"):
            assert current_uid() == "u_bob"


def test_acting_as_restores_uncached_state():
    with signed_in("u_alice"):
        # No current_uid() call before the swap: the cache slot is empty,
        # and it must still be empty (not "u_bob") after the swap exits.
        with acting_as("u_bob"):
            assert current_uid() == "u_bob"
        assert current_uid() == "u_alice"


def test_acting_as_nests_level_by_level():
    with signed_in("u_a"):
        with acting_as("u_b"):
            with acting_as("u_c"):
                assert current_uid() == "u_c"
            assert current_uid() == "u_b"
        assert current_uid() == "u_a"


def test_acting_as_restores_on_exception():
    with signed_in("u_alice"):
        with pytest.raises(ValueError):
            with acting_as("u_bob"):
                raise ValueError("boom")
        assert current_uid() == "u_alice"


def test_acting_as_outside_signed_in_raises():
    with pytest.raises(RuntimeError):
        with acting_as("u_bob"):
            pass


def test_acting_as_extras_follow_the_identity():
    with signed_in("u_admin", extras={"role": "admin"}):
        with acting_as("u_viewer", extras={"role": "viewer"}):
            assert identity_extras()["role"] == "viewer"
        assert identity_extras()["role"] == "admin"


def test_acting_as_without_extras_does_not_inherit_outer_extras():
    with signed_in("u_admin", extras={"role": "admin"}):
        with acting_as("u_other"):
            assert dict(identity_extras()) == {}
        assert identity_extras()["role"] == "admin"


def test_acting_as_with_extras_restores_absent_outer_extras():
    """Outer signed_in without extras: after an acting_as(extras=...) block
    exits, identity_extras() must read as absent/empty again, never as a
    leaked restore sentinel."""
    with signed_in("u_outer"):
        with acting_as("u_bob", extras={"role": "admin"}):
            assert identity_extras()["role"] == "admin"
        assert dict(identity_extras()) == {}


def test_acting_as_restores_extras_on_exception():
    with signed_in("u_admin", extras={"role": "admin"}):
        with pytest.raises(ValueError):
            with acting_as("u_other", extras={"role": "viewer"}):
                raise ValueError("boom")
        assert identity_extras()["role"] == "admin"
