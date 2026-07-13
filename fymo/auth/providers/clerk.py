"""Hosted-token provider (Clerk / Auth0-hosted).

The IdP owns the login UI and the session; fymo issues no session of its own.
Every request carries the provider's JWT (cookie or Authorization: Bearer),
and identity is resolved by *verifying that token per request* — the Axis-B
seam. First sight of a subject provisions a local user.

Production verification is RS256-over-JWKS, which needs a crypto library, so
the verifier is injectable: the default lazily uses PyJWT (optional dep) when
present, and tests inject a fake. Core stays dependency-free.
"""
from __future__ import annotations

from typing import Callable, Optional

from fymo.auth.context import get_user_store
from fymo.auth.providers.base import BaseProvider
from fymo.auth.providers.oauth import resolve_or_create_user
from fymo.auth.store import User

# verify(token) -> claims dict, or None if the token is invalid/expired.
Verifier = Callable[[str], Optional[dict]]


class ClerkProvider(BaseProvider):
    id = "clerk"

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience: Optional[str] = None,
        cookie_name: str = "__session",
        verify: Optional[Verifier] = None,
    ):
        self.issuer = issuer
        self.jwks_url = jwks_url
        self.audience = audience
        self.cookie_name = cookie_name
        self._verify = verify or _jwks_verifier(jwks_url, issuer, audience)

    @classmethod
    def from_config(cls, opts: dict) -> "ClerkProvider":
        return cls(
            issuer=opts["issuer"],
            jwks_url=opts["jwks_url"],
            audience=opts.get("audience"),
            cookie_name=opts.get("cookie_name", "__session"),
        )

    def _token(self, event: dict) -> Optional[str]:
        cookie = event.get("cookies", {}).get(self.cookie_name)
        if cookie:
            return cookie
        auth = event.get("headers", {}).get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    def resolve_session(self, event: dict) -> Optional[User]:
        token = self._token(event)
        if not token:
            return None
        claims = self._verify(token)
        if not claims:
            return None
        sub = claims.get("sub")
        if not sub:
            return None
        return resolve_or_create_user(
            get_user_store(), self.id, str(sub), claims.get("email"),
            bool(claims.get("email_verified")),
        )


def _jwks_verifier(jwks_url: str, issuer: str, audience: Optional[str]) -> Verifier:
    """Default RS256/JWKS verifier. Requires the optional `pyjwt[crypto]` extra;
    raises a clear error at first use if it isn't installed."""

    def verify(token: str) -> Optional[dict]:
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError as e:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "Clerk token verification needs the 'pyjwt[crypto]' package; "
                "install it or pass a custom verify= to ClerkProvider"
            ) from e
        try:
            signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(
                token, signing_key.key, algorithms=["RS256"],
                issuer=issuer, audience=audience,
                options={"verify_aud": audience is not None},
            )
        except Exception:
            return None

    return verify
