"""Auth packaging boundary (issue #59): the password provider stays a
zero-dependency default; Clerk's JWKS verification needs pyjwt[crypto],
shipped as the `fymo[clerk]` extra. Its absence must fail loudly the moment
a ClerkProvider is built (i.e. at FymoApp boot, via
fymo/auth/providers/registry.py), not the first time someone tries to log
in — see tests/core/test_auth_boot_extras.py for the full FymoApp-level
proof of that.
"""
import sys

import pytest

from fymo.auth.providers.clerk import ClerkProvider, _pyjwt_available
from fymo.auth.providers.password import PasswordProvider
from fymo.auth.providers.registry import build_providers


def test_build_providers_default_is_password_only():
    providers = build_providers(None)
    assert len(providers) == 1
    assert isinstance(providers[0], PasswordProvider)


def test_password_only_app_never_imports_pyjwt_or_cryptography():
    """Zero-extras acceptance criterion. The dev environment has pyjwt and
    cryptography installed (so the real-crypto test below can exercise
    them), so this only proves anything if we first evict them and confirm
    the password-only path never pulls them back in."""
    for name in ("jwt", "cryptography"):
        sys.modules.pop(name, None)
    build_providers(None)
    build_providers(["password"])
    assert "jwt" not in sys.modules
    assert "cryptography" not in sys.modules


def test_clerk_construction_fails_loudly_when_pyjwt_missing(monkeypatch):
    monkeypatch.setattr("fymo.auth.providers.clerk._pyjwt_available", lambda: False)
    with pytest.raises(RuntimeError, match=r"pip install 'fymo\[clerk\]'"):
        ClerkProvider(issuer="https://x.clerk.accounts.dev", jwks_url="https://x/jwks")


def test_clerk_construction_succeeds_when_pyjwt_available(monkeypatch):
    monkeypatch.setattr("fymo.auth.providers.clerk._pyjwt_available", lambda: True)
    prov = ClerkProvider(issuer="https://x.clerk.accounts.dev", jwks_url="https://x/jwks")
    assert prov.issuer == "https://x.clerk.accounts.dev"


def test_clerk_construction_with_explicit_verify_skips_the_pyjwt_check(monkeypatch):
    """A caller supplying its own verify= (every test in test_clerk.py does
    this) never touches the lazy JWKS verifier, so construction must not
    require pyjwt at all -- the check only guards the default verifier."""
    def _boom():
        raise AssertionError("_pyjwt_available must not be called when verify= is given")

    monkeypatch.setattr("fymo.auth.providers.clerk._pyjwt_available", _boom)
    ClerkProvider(issuer="https://x", jwks_url="https://x/jwks", verify=lambda tok: None)


def test_build_providers_from_config_fails_loudly_when_pyjwt_missing(monkeypatch):
    """The same failure must surface through the fymo.yml config path
    (registry.build_providers), which is what FymoApp.__init__ actually
    calls -- not just through direct ClerkProvider() construction."""
    monkeypatch.setenv("CLERK_ISSUER", "https://x.clerk.accounts.dev")
    monkeypatch.setattr("fymo.auth.providers.clerk._pyjwt_available", lambda: False)
    with pytest.raises(RuntimeError, match=r"pip install 'fymo\[clerk\]'"):
        build_providers([{"type": "clerk"}])


def test_pyjwt_available_reflects_real_environment():
    """Sanity check on the detector itself, unmocked: this dev environment
    has pyjwt[crypto] installed (added as a dev dependency specifically so
    the real-crypto tests below get exercised instead of skipped), so the
    real check must report True."""
    assert _pyjwt_available() is True


# --- Real crypto path: proves `pip install 'fymo[clerk]'` restores today's
# behavior identically, not just that construction doesn't raise. ---
jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")


def test_jwks_verifier_round_trips_a_genuinely_signed_token(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt import PyJWKClient

    from fymo.auth.providers.clerk import _jwks_verifier

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"sub": "user-1", "iss": "https://x.clerk.accounts.dev", "aud": "my-app",
         "email": "a@example.com", "email_verified": True},
        private_key, algorithm="RS256", headers={"kid": "test-key"},
    )

    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    # Only the network JWKS fetch is faked (no real HTTP call); the actual
    # RS256 decode + signature verification below runs for real through the
    # installed pyjwt/cryptography.
    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt",
        lambda self, tok: _FakeSigningKey(private_key.public_key()),
    )

    verify = _jwks_verifier("https://x/jwks", "https://x.clerk.accounts.dev", "my-app")

    claims = verify(token)
    assert claims is not None
    assert claims["sub"] == "user-1"
    assert claims["email"] == "a@example.com"

    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert verify(tampered) is None


def test_jwks_verifier_rejects_wrong_issuer(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt import PyJWKClient

    from fymo.auth.providers.clerk import _jwks_verifier

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"sub": "user-1", "iss": "https://not-the-configured-issuer.example", "aud": "my-app"},
        private_key, algorithm="RS256", headers={"kid": "test-key"},
    )

    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt",
        lambda self, tok: _FakeSigningKey(private_key.public_key()),
    )

    verify = _jwks_verifier("https://x/jwks", "https://x.clerk.accounts.dev", "my-app")
    assert verify(token) is None
