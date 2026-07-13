"""OAuth Authorization-Code flow, driven end to end against a fake IdP transport."""
import urllib.parse
from pathlib import Path

import pytest

from fymo.auth import context as auth_context
from fymo.auth.providers.oauth import GoogleProvider
from fymo.auth.store import SqliteUserStore
from fymo.remote.identity import set_secret


class FakeTransport:
    """Stands in for the IdP: returns a canned token and userinfo."""

    def __init__(self, userinfo: dict):
        self.userinfo = userinfo
        self.token_calls = []

    def post_form(self, url, fields):
        self.token_calls.append((url, fields))
        return {"access_token": "fake-access-token"}

    def get_json(self, url, bearer):
        return self.userinfo


def _call(handler, query_string: str):
    captured = {}
    def sr(status, headers):
        captured["status"] = status
        captured["headers"] = headers
    body = b"".join(handler({"QUERY_STRING": query_string, "wsgi.url_scheme": "http"}, sr))
    return captured["status"], captured["headers"], body


def _header(headers, name):
    return next((v for k, v in headers if k.lower() == name.lower()), None)


@pytest.fixture
def wired(tmp_path: Path):
    set_secret(b"x" * 32)
    store = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(store)
    return store


def _google(transport):
    return GoogleProvider(
        client_id="cid", client_secret="sec",
        redirect_uri="https://app.example/auth/google/callback",
        transport=transport,
    )


def test_start_redirects_to_idp_with_pkce_and_signed_state(wired):
    prov = _google(FakeTransport({}))
    status, headers, _ = _call(prov._start, "next=/dashboard")
    assert status.startswith("302")
    loc = _header(headers, "Location")
    assert loc.startswith(prov.authorize_endpoint)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    assert q["client_id"] == ["cid"]
    assert q["code_challenge_method"] == ["S256"]
    assert "code_challenge" in q
    assert q["state"]  # signed state present


def test_callback_creates_user_links_identity_and_sets_session(wired):
    store = wired
    transport = FakeTransport({"sub": "g-sub-1", "email": "newuser@example.com", "email_verified": True})
    prov = _google(transport)

    # Obtain a valid signed state from the real start step.
    _, start_headers, _ = _call(prov._start, "next=/dashboard")
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(_header(start_headers, "Location")).query
    )["state"][0]

    status, headers, _ = _call(
        prov._callback, urllib.parse.urlencode({"code": "auth-code", "state": state})
    )
    assert status.startswith("302")
    assert _header(headers, "Location") == "/dashboard"
    assert _header(headers, "Set-Cookie").startswith("fymo_session=")

    # The token exchange sent the PKCE verifier + our client credentials.
    _, fields = transport.token_calls[0]
    assert fields["grant_type"] == "authorization_code"
    assert fields["code"] == "auth-code"
    assert "code_verifier" in fields

    # A user was created and linked to the Google identity.
    user = store.get_by_identity("google", "g-sub-1")
    assert user is not None
    assert user.email == "newuser@example.com"
    assert user.password_hash is None  # provider-authenticated, no password


def test_callback_links_to_existing_user_by_verified_email(wired):
    store = wired
    existing = store.create("known@example.com", "scrypt$hash")
    prov = _google(FakeTransport({"sub": "g-sub-2", "email": "known@example.com", "email_verified": True}))

    _, sh, _ = _call(prov._start, "next=/")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(_header(sh, "Location")).query)["state"][0]
    _call(prov._callback, urllib.parse.urlencode({"code": "c", "state": state}))

    linked = store.get_by_identity("google", "g-sub-2")
    assert linked.id == existing.id  # linked, not duplicated


def test_unverified_email_does_not_hijack_existing_account(wired):
    """An IdP account carrying a victim's UNVERIFIED email must not link into the
    victim's existing account — the classic OAuth account-takeover vector."""
    store = wired
    victim = store.create("victim@example.com", "scrypt$hash")
    # Attacker's identity: victim's email, but no email_verified assertion.
    prov = _google(FakeTransport({"sub": "attacker-sub", "email": "victim@example.com"}))

    _, sh, _ = _call(prov._start, "next=/")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(_header(sh, "Location")).query)["state"][0]
    _call(prov._callback, urllib.parse.urlencode({"code": "c", "state": state}))

    linked = store.get_by_identity("google", "attacker-sub")
    assert linked is not None
    assert linked.id != victim.id  # must NOT take over the victim's account


def test_open_redirect_via_next_is_neutralized(wired):
    """`next=//evil.com` is protocol-relative and must not redirect off-site."""
    prov = _google(FakeTransport({"sub": "r-1", "email": "r@example.com", "email_verified": True}))
    _, sh, _ = _call(prov._start, urllib.parse.urlencode({"next": "//evil.com"}))
    state = urllib.parse.parse_qs(urllib.parse.urlparse(_header(sh, "Location")).query)["state"][0]
    status, headers, _ = _call(prov._callback, urllib.parse.urlencode({"code": "c", "state": state}))
    assert status.startswith("302")
    assert _header(headers, "Location") == "/"


def test_callback_rejects_tampered_state(wired):
    prov = _google(FakeTransport({"sub": "x", "email": "x@x.com"}))
    status, _, _ = _call(
        prov._callback, urllib.parse.urlencode({"code": "c", "state": "forged.deadbeef"})
    )
    assert status.startswith("400")


def test_google_builds_from_config_env_and_exposes_routes(monkeypatch):
    from fymo.auth.providers.registry import build_providers
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    providers = build_providers([{
        "type": "google",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "redirect_uri": "https://app.example/auth/google/callback",
    }])
    g = providers[0]
    assert g.id == "google"
    assert g.client_id == "cid" and g.client_secret == "sec"
    routes = {(r.method, r.path) for r in g.http_routes()}
    assert ("GET", "/auth/google/start") in routes
    assert ("GET", "/auth/google/callback") in routes
