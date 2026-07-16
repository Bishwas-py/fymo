"""fymo.testing.signed_in / acting_as: fake authenticated sessions for tests."""
import pytest

from fymo.auth import context as auth_context
from fymo.auth.context import current_user, register_session_resolver, reset_session_resolvers
from fymo.remote.identity import current_uid
from fymo.testing import acting_as, make_user, signed_in


def test_signed_in_default_user_resolves_via_current_user():
    with signed_in() as user:
        assert current_user() == user
        assert current_user().email == user.email


def test_signed_in_custom_user():
    alice = make_user(email="alice@example.com")
    with signed_in(alice):
        resolved = current_user()
        assert resolved is alice
        assert resolved.email == "alice@example.com"


def test_make_user_assigns_unique_ids():
    a = make_user()
    b = make_user()
    assert a.id != b.id


def test_make_user_accepts_overrides():
    u = make_user(email="x@example.com", id=42, email_verified=False)
    assert u.id == 42
    assert u.email == "x@example.com"
    assert u.email_verified is False


def test_signed_in_provides_request_scope_uid():
    with signed_in(uid="u_custom"):
        assert current_uid() == "u_custom"


def test_signed_in_default_uid_derives_from_user():
    user = make_user(id=7)
    with signed_in(user):
        assert current_uid() == "u_test7"


def test_sequential_signed_in_users_get_distinct_uids():
    with signed_in(make_user(email="one@example.com")):
        uid_one = current_uid()
    with signed_in(make_user(email="two@example.com")):
        uid_two = current_uid()
    assert uid_one != uid_two


def test_current_user_raises_outside_block():
    with signed_in():
        pass
    with pytest.raises(RuntimeError):
        current_user()


def test_acting_as_swaps_and_restores():
    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")
    with signed_in(alice):
        assert current_user() is alice
        with acting_as(bob):
            assert current_user() is bob
        assert current_user() is alice


def test_acting_as_swaps_uid_with_the_user():
    alice = make_user(id=11)
    bob = make_user(id=22)
    with signed_in(alice):
        assert current_uid() == "u_test11"
        with acting_as(bob):
            assert current_uid() == "u_test22"
        assert current_uid() == "u_test11"


def test_acting_as_accepts_uid_override():
    bob = make_user(email="bob@example.com")
    with signed_in(uid="u_outer"):
        with acting_as(bob, uid="u_inner"):
            assert current_uid() == "u_inner"
        assert current_uid() == "u_outer"


def test_acting_as_nested_uids_restore_level_by_level():
    a = make_user(id=101)
    b = make_user(id=102)
    c = make_user(id=103)
    with signed_in(a):
        with acting_as(b):
            with acting_as(c):
                assert current_uid() == "u_test103"
            assert current_uid() == "u_test102"
        assert current_uid() == "u_test101"


def test_acting_as_restores_uid_on_exception():
    alice = make_user(id=31)
    bob = make_user(id=32)
    with signed_in(alice):
        with pytest.raises(ValueError):
            with acting_as(bob):
                raise ValueError("boom")
        assert current_uid() == "u_test31"


def test_acting_as_yields_the_user():
    bob = make_user(email="bob@example.com")
    with signed_in():
        with acting_as(bob) as inner:
            assert inner is bob


def test_acting_as_nests():
    a = make_user(email="a@example.com")
    b = make_user(email="b@example.com")
    c = make_user(email="c@example.com")
    with signed_in(a):
        with acting_as(b):
            with acting_as(c):
                assert current_user() is c
            assert current_user() is b
        assert current_user() is a


def test_acting_as_outside_signed_in_raises():
    bob = make_user(email="bob@example.com")
    with pytest.raises(RuntimeError):
        with acting_as(bob):
            pass


def test_acting_as_restores_on_exception():
    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")
    with signed_in(alice):
        with pytest.raises(ValueError):
            with acting_as(bob):
                raise ValueError("boom")
        assert current_user() is alice


def test_signed_in_leaves_resolver_registry_as_found():
    sentinel = lambda event: None
    register_session_resolver(sentinel)
    try:
        assert auth_context._session_resolvers == [sentinel]
        with signed_in():
            pass
        assert auth_context._session_resolvers == [sentinel]
    finally:
        reset_session_resolvers()


def test_signed_in_cleans_up_when_body_raises():
    from fymo.remote.context import _current_event

    resolvers_before = list(auth_context._session_resolvers)
    event_before = _current_event.get()
    with pytest.raises(ValueError):
        with signed_in():
            raise ValueError("boom")
    assert auth_context._session_resolvers == resolvers_before
    assert _current_event.get() == event_before
    with pytest.raises(RuntimeError):
        current_user()


def test_signed_in_blocks_nest():
    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")
    with signed_in(alice):
        with signed_in(bob):
            assert current_user() is bob
        assert current_user() is alice
    assert auth_context._session_resolvers == []
