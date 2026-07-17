"""Identity resolvers (issue #80, phase 1): Identity, ResolverEvent,
@identify, current_uid(), and the promoted signed-token primitives.

The new surface coexists with the legacy User/UserStore world in this
phase; current_uid() walks only the @identify chain and never consults
the legacy _session_resolvers or the fymo-session cookie resolver.
"""
import dataclasses

import pytest

from fymo.auth import (
    Identity,
    ResolverEvent,
    current_uid,
    hash_password,
    identify,
    sign_token,
    verify_password,
    verify_token,
)
from fymo.auth.context import register_session_resolver, reset_session_resolvers
from fymo.auth.identity import reset_identity_resolvers, _identity_resolvers
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def clean_registry():
    set_secret(b"x" * 32)
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()
    reset_session_resolvers()


def _scope(environ=None):
    return request_scope(uid="u_legacy", environ=environ or {})


# --------------- Identity ---------------


def test_identity_is_frozen():
    ident = Identity(uid="u1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.uid = "u2"


def test_identity_equality_by_uid():
    assert Identity(uid="u1") == Identity(uid="u1")
    assert Identity(uid="u1") != Identity(uid="u2")


def test_identity_has_only_uid_field():
    assert [f.name for f in dataclasses.fields(Identity)] == ["uid"]


# --------------- ResolverEvent ---------------


def test_resolver_event_shape():
    event = ResolverEvent(
        remote_addr="10.0.0.1",
        cookies={"a": "1"},
        headers={"x-h": "v"},
        scheme="https",
    )
    assert event.remote_addr == "10.0.0.1"
    assert event.cookies == {"a": "1"}
    assert event.headers == {"x-h": "v"}
    assert event.scheme == "https"
    assert [f.name for f in dataclasses.fields(ResolverEvent)] == [
        "remote_addr",
        "cookies",
        "headers",
        "scheme",
    ]


def test_resolver_event_is_frozen():
    event = ResolverEvent(remote_addr="", cookies={}, headers={}, scheme="http")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.scheme = "https"


# --------------- @identify registration ---------------


def test_identify_returns_the_function():
    def resolver(event):
        return None

    assert identify(resolver) is resolver


def test_resolvers_chain_in_registration_order_first_non_none_wins():
    calls = []

    @identify
    def first(event):
        calls.append("first")
        return None

    @identify
    def second(event):
        calls.append("second")
        return Identity(uid="from-second")

    @identify
    def third(event):
        calls.append("third")
        return Identity(uid="from-third")

    with _scope():
        assert current_uid() == "from-second"
    assert calls == ["first", "second"]


def test_identify_reload_safe_same_definition_site_registers_once():
    src = (
        "from fymo.auth import identify, Identity\n"
        "@identify\n"
        "def resolver(event):\n"
        "    return Identity(uid='reloaded')\n"
    )
    code = compile(src, "/app/auth/resolver.py", "exec")
    ns1 = {"__name__": "app.auth.resolver"}
    exec(code, ns1)
    ns2 = {"__name__": "app.auth.resolver"}
    exec(code, ns2)

    assert len(_identity_resolvers) == 1
    assert _identity_resolvers[0] is ns2["resolver"]


def test_identify_distinct_definition_sites_both_register():
    @identify
    def one(event):
        return None

    @identify
    def two(event):
        return None

    assert len(_identity_resolvers) == 2


def test_reset_identity_resolvers_clears_chain():
    @identify
    def resolver(event):
        return Identity(uid="u1")

    reset_identity_resolvers()
    assert _identity_resolvers == []
    with _scope():
        assert current_uid() is None


# --------------- current_uid ---------------


def test_current_uid_returns_uid_from_matching_resolver():
    @identify
    def by_header(event):
        if event.headers.get("x-api-key") == "k1":
            return Identity(uid="user-42")
        return None

    with _scope({"HTTP_X_API_KEY": "k1"}):
        assert current_uid() == "user-42"


def test_current_uid_none_when_no_resolver_matches():
    @identify
    def never(event):
        return None

    with _scope():
        assert current_uid() is None


def test_current_uid_none_when_no_resolvers_registered():
    with _scope():
        assert current_uid() is None


def test_current_uid_raises_outside_request_scope():
    with pytest.raises(RuntimeError):
        current_uid()


def test_current_uid_resolution_cached_per_request():
    calls = []

    @identify
    def resolver(event):
        calls.append(1)
        return Identity(uid="u1")

    with _scope():
        assert current_uid() == "u1"
        assert current_uid() == "u1"
    assert calls == [1]


def test_current_uid_anonymous_resolution_cached_per_request():
    calls = []

    @identify
    def resolver(event):
        calls.append(1)
        return None

    with _scope():
        assert current_uid() is None
        assert current_uid() is None
    assert calls == [1]


def test_current_uid_resolved_fresh_per_scope():
    uids = iter(["a", "b"])

    @identify
    def resolver(event):
        return Identity(uid=next(uids))

    with _scope():
        assert current_uid() == "a"
    with _scope():
        assert current_uid() == "b"


def test_current_uid_sees_request_event_fields():
    seen = {}

    @identify
    def resolver(event):
        seen["remote_addr"] = event.remote_addr
        seen["cookie"] = event.cookies.get("sid")
        seen["scheme"] = event.scheme
        return None

    environ = {
        "REMOTE_ADDR": "192.0.2.7",
        "HTTP_COOKIE": "sid=abc",
        "wsgi.url_scheme": "https",
    }
    with _scope(environ):
        current_uid()
    assert seen == {"remote_addr": "192.0.2.7", "cookie": "abc", "scheme": "https"}


def test_current_uid_ignores_legacy_session_resolvers():
    sentinel = object()
    register_session_resolver(lambda event: sentinel)
    with _scope():
        assert current_uid() is None


# --------------- promoted primitives ---------------


def test_password_primitives_round_trip():
    stored = hash_password("s3cret")
    assert verify_password("s3cret", stored) is True
    assert verify_password("wrong", stored) is False


def test_sign_token_round_trips():
    token = sign_token("user-42")
    assert verify_token(token) == "user-42"


def test_sign_token_uid_may_contain_delimiters():
    uid = "org:acme.user.42"
    assert verify_token(sign_token(uid)) == uid


def test_verify_token_rejects_tampering():
    token = sign_token("user-42")
    assert verify_token(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
    assert verify_token("") is None
    assert verify_token("not.a.token") is None


def test_verify_token_rejects_expired():
    token = sign_token("user-42", issued_at=1_000_000)
    assert verify_token(token, now=1_000_000 + 10) == "user-42"
    assert verify_token(token, max_age=60, now=1_000_000 + 61) is None
