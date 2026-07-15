"""ClerkProvider zero-config: derive issuer/jwks_url from env, implement
is_configured() so `required: auto` actually works for Clerk (issue #28)."""
import base64

import pytest

from fymo.auth.providers.clerk import ClerkProvider
from fymo.auth.providers.registry import build_providers

# pk_test_<base64("clerk.example.com$")>
PUBLISHABLE_KEY = "pk_test_" + base64.b64encode(b"clerk.example.com$").decode()


def test_from_config_uses_explicit_issuer_and_jwks_url(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("PUBLIC_CLERK_PUBLISHABLE_KEY", raising=False)
    prov = ClerkProvider.from_config({
        "issuer": "https://x.clerk.accounts.dev",
        "jwks_url": "https://x.example/jwks",
    })
    assert prov.issuer == "https://x.clerk.accounts.dev"
    assert prov.jwks_url == "https://x.example/jwks"


def test_from_config_derives_jwks_url_from_explicit_issuer(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("PUBLIC_CLERK_PUBLISHABLE_KEY", raising=False)
    prov = ClerkProvider.from_config({"issuer": "https://x.clerk.accounts.dev"})
    assert prov.jwks_url == "https://x.clerk.accounts.dev/.well-known/jwks.json"


def test_from_config_reads_issuer_from_clerk_issuer_env(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", "https://env.clerk.accounts.dev")
    monkeypatch.delenv("PUBLIC_CLERK_PUBLISHABLE_KEY", raising=False)
    prov = ClerkProvider.from_config({})
    assert prov.issuer == "https://env.clerk.accounts.dev"
    assert prov.jwks_url == "https://env.clerk.accounts.dev/.well-known/jwks.json"


def test_from_config_derives_issuer_from_publishable_key_env(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    prov = ClerkProvider.from_config({})
    assert prov.issuer == "https://clerk.example.com"
    assert prov.jwks_url == "https://clerk.example.com/.well-known/jwks.json"


def test_from_config_clerk_issuer_env_wins_over_publishable_key(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", "https://explicit.clerk.accounts.dev")
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    prov = ClerkProvider.from_config({})
    assert prov.issuer == "https://explicit.clerk.accounts.dev"


def test_from_config_explicit_opt_wins_over_conflicting_env(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", "https://env.clerk.accounts.dev")
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    prov = ClerkProvider.from_config({"issuer": "https://yml.clerk.accounts.dev"})
    assert prov.issuer == "https://yml.clerk.accounts.dev"


def test_from_config_explicit_jwks_url_wins_over_derived(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", "https://env.clerk.accounts.dev")
    prov = ClerkProvider.from_config({"jwks_url": "https://custom/jwks.json"})
    assert prov.jwks_url == "https://custom/jwks.json"


def test_from_config_raises_clear_error_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("PUBLIC_CLERK_PUBLISHABLE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CLERK_ISSUER"):
        ClerkProvider.from_config({})


def test_is_configured_false_with_no_env(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("PUBLIC_CLERK_PUBLISHABLE_KEY", raising=False)
    assert ClerkProvider.is_configured() is False


def test_is_configured_true_with_clerk_issuer_env(monkeypatch):
    monkeypatch.setenv("CLERK_ISSUER", "https://env.clerk.accounts.dev")
    assert ClerkProvider.is_configured() is True


def test_is_configured_true_with_publishable_key_env(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    assert ClerkProvider.is_configured() is True


def test_is_configured_false_for_malformed_publishable_key(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", "not-a-real-key")
    assert ClerkProvider.is_configured() is False


def test_is_configured_false_for_pk_prefixed_key_with_undecodable_body(monkeypatch):
    """Right shape (pk_test_<...>) but the body isn't valid base64 at all,
    as opposed to the wrong-shape case above (no pk_<env>_ prefix)."""
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_!!!not-base64!!!")
    assert ClerkProvider.is_configured() is False


def test_required_auto_skips_clerk_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("PUBLIC_CLERK_PUBLISHABLE_KEY", raising=False)
    providers = build_providers([{"type": "clerk", "required": "auto"}])
    assert providers == []


def test_required_auto_includes_clerk_when_configured_via_publishable_key(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.setenv("PUBLIC_CLERK_PUBLISHABLE_KEY", PUBLISHABLE_KEY)
    providers = build_providers([{"type": "clerk", "required": "auto"}])
    assert len(providers) == 1
    assert providers[0].issuer == "https://clerk.example.com"
