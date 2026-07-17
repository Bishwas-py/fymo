"""Identity resolvers (issue #80): Identity, ResolverEvent, @identify,
current_uid(), and the promoted signed-token primitives.
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
from fymo.auth.identity import reset_identity_resolvers, _identity_resolvers
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def clean_registry():
    set_secret(b"x" * 32)
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()


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


# --------------- resolver return-type validation ---------------


def test_resolver_returning_str_raises_typeerror():
    @identify
    def bad(event):
        return "user-42"

    with _scope():
        with pytest.raises(TypeError) as exc_info:
            current_uid()
    msg = str(exc_info.value)
    assert "bad" in msg
    assert "str" in msg
    assert "fymo.auth.Identity(uid=...) or None" in msg


def test_resolver_returning_duck_typed_object_raises_typeerror():
    class Duck:
        uid = "12345"

    @identify
    def quacks(event):
        return Duck()

    with _scope():
        with pytest.raises(TypeError) as exc_info:
            current_uid()
    msg = str(exc_info.value)
    assert "quacks" in msg
    assert "Duck" in msg


def test_resolver_returning_identity_or_none_is_accepted():
    @identify
    def anon(event):
        return None

    @identify
    def ok(event):
        return Identity(uid="u1")

    with _scope():
        assert current_uid() == "u1"


def test_registered_identity_resolvers_snapshot():
    from fymo.auth.identity import registered_identity_resolvers

    assert registered_identity_resolvers() == ()

    @identify
    def resolver(event):
        return None

    snapshot = registered_identity_resolvers()
    assert snapshot == (resolver,)
    # A snapshot, not the live list: mutating it must not touch the chain.
    assert snapshot is not _identity_resolvers


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


def test_verify_token_max_age_exact_boundary():
    token = sign_token("user-42", issued_at=1_000_000)
    assert verify_token(token, max_age=60, now=1_000_060) == "user-42"
    assert verify_token(token, max_age=60, now=1_000_061) is None


def test_verify_token_rejects_uid_segment_tampered_alone():
    from fymo.auth.verify_token import _b64url_encode

    token = sign_token("user-42", issued_at=1_000_000)
    _, issued_str, sig = token.split(".")
    forged = f"{_b64url_encode('user-43')}.{issued_str}.{sig}"
    assert forged != token
    assert verify_token(forged, now=1_000_010) is None


def test_verify_token_rejects_issued_at_segment_tampered_alone():
    token = sign_token("user-42", issued_at=1_000_000)
    uid_b64, issued_str, sig = token.split(".")
    forged = f"{uid_b64}.{int(issued_str) + 1}.{sig}"
    assert verify_token(forged, now=1_000_010) is None


# --------------- domain separation across HMAC purposes ---------------


def test_token_signed_under_another_prefix_never_passes_verify_token():
    """The "token:" prefix is part of the signed payload: a token minted by
    any other HMAC purpose sharing FYMO_SECRET (a different prefix over the
    same wire shape) must not verify here."""
    import base64
    import hmac as hmac_mod
    from hashlib import sha256

    from fymo.auth.verify_token import _b64url_encode, _get_secret

    uid_b64 = _b64url_encode("user-42")
    issued_at = 1_000_000
    payload = f"other:{uid_b64}:{issued_at}".encode("utf-8")
    mac = hmac_mod.new(_get_secret(), payload, sha256).digest()
    sig = base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")[:22]
    forged = f"{uid_b64}.{issued_at}.{sig}"
    assert verify_token(forged, now=issued_at + 10) is None
