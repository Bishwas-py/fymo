"""Hosted-token provider (Clerk / Auth0-hosted).

The IdP owns the login UI and the session; fymo issues no session of its own.
Every request carries the provider's JWT (cookie or Authorization: Bearer),
and identity is resolved by *verifying that token per request* — the Axis-B
seam. First sight of a subject provisions a local user.

Production verification is RS256-over-JWKS, which needs a crypto library, so
the verifier is injectable: the default lazily uses PyJWT (optional dep) when
present, and tests inject a fake. Core stays dependency-free.

Packaging (issue #59): pyjwt[crypto] ships as the `fymo[clerk]` extra, never
a hard dependency of fymo itself. A caller supplying their own verify=
(every test in this package does) never needs it at all. When the default
verifier is going to be used, its presence is checked eagerly in __init__,
at provider construction, which fymo.yml's `type: clerk` reaches from
FymoApp.__init__, so a missing extra is a loud boot-time failure instead
of surfacing only the first time someone logs in.

Migration note: before this extra existed, `type: clerk` worked from a bare
`pip install fymo` as long as pyjwt[crypto] happened to already be present.
There is no separate deprecation-warning phase for that "present but never
declared via the extra" state. At runtime there is no reliable way to tell
"installed because fymo[clerk] was requested" apart from "installed some
other way" (pip/uv don't record per-dependency install provenance anywhere
`importlib.metadata` exposes), so a warning aimed only at the second case
would either misfire on properly-installed extras or never fire at all.
Both states behave identically here: the deps are present, verification
works, nothing is disabled. The actual fix is the loud failure above for the
one state that matters, truly missing, which is strictly better than
today's silent-until-first-login gap regardless of how someone got pyjwt.
"""
from __future__ import annotations

import base64
import os
from importlib.util import find_spec
from typing import Callable, Optional

from fymo.auth.context import get_user_store
from fymo.auth.providers.base import BaseProvider
from fymo.auth.providers.oauth import resolve_or_create_user
from fymo.auth.store import User

# verify(token) -> claims dict, or None if the token is invalid/expired.
Verifier = Callable[[str], Optional[dict]]

_ISSUER_ENV = "CLERK_ISSUER"
_PUBLISHABLE_KEY_ENV = "PUBLIC_CLERK_PUBLISHABLE_KEY"
_INSTALL_HINT = "pip install 'fymo[clerk]'"


def _pyjwt_available() -> bool:
    """Whether the default JWKS verifier can actually run: pyjwt itself, plus
    a real crypto backend for RS256 (pyjwt's `cryptography` extra: `import
    jwt` alone succeeds without it, RS256 only fails once you try to use it).
    find_spec (not a real import) so checking never has the side effect of
    loading either package, and tests can monkeypatch this one function
    instead of faking module presence in sys.modules."""
    return find_spec("jwt") is not None and find_spec("cryptography") is not None


def _issuer_from_publishable_key(key: str) -> Optional[str]:
    """Clerk publishable keys (`pk_test_<b64>` / `pk_live_<b64>`) base64-encode
    the Frontend API domain, terminated with a literal `$` -- Clerk's own
    documented key shape, e.g. `pk_test_Y2xlcmsuZXhhbXBsZS5jb20k` decodes to
    `clerk.example.com$`. Returns None on any key that doesn't match, rather
    than raising, so callers (is_configured included) can treat it as "not
    configured" instead of crashing on a typo'd key."""
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != "pk":
        return None
    encoded = parts[2]
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        domain = base64.b64decode(padded).decode("ascii").rstrip("$")
    except Exception:
        return None
    return f"https://{domain}" if domain else None


def _issuer_from_env() -> Optional[str]:
    """CLERK_ISSUER wins when set; otherwise derive it from the publishable
    key, which every Clerk app already has lying around in its frontend env."""
    issuer = os.environ.get(_ISSUER_ENV)
    if issuer:
        return issuer
    key = os.environ.get(_PUBLISHABLE_KEY_ENV)
    return _issuer_from_publishable_key(key) if key else None


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
        if verify is None:
            if not _pyjwt_available():
                raise RuntimeError(
                    "Clerk auth (type: clerk) needs the 'pyjwt[crypto]' package "
                    f"for RS256/JWKS verification. Install it with: {_INSTALL_HINT}"
                )
            verify = _jwks_verifier(jwks_url, issuer, audience)
        self._verify = verify

    @classmethod
    def from_config(cls, opts: dict) -> "ClerkProvider":
        issuer = opts.get("issuer") or _issuer_from_env()
        if not issuer:
            raise RuntimeError(
                f"ClerkProvider has no issuer: set {_ISSUER_ENV}, or "
                f"{_PUBLISHABLE_KEY_ENV} (Clerk's pk_test_/pk_live_ key) so it "
                "can be derived, or pass issuer= explicitly in fymo.yml"
            )
        return cls(
            issuer=issuer,
            jwks_url=opts.get("jwks_url") or f"{issuer}/.well-known/jwks.json",
            audience=opts.get("audience"),
            cookie_name=opts.get("cookie_name", "__session"),
        )

    @classmethod
    def is_configured(cls) -> bool:
        """Only consulted when a fymo.yml entry opts in with `required: auto`
        (see BaseProvider); reasons purely from the environment since the
        registry calls this with no opts, so an explicit literal `issuer:` in
        yml without either env var set won't count as configured here -- that
        app doesn't need `required: auto` anyway, it already knows it's
        configured."""
        return _issuer_from_env() is not None

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
    """Default RS256/JWKS verifier. Requires the optional `pyjwt[crypto]` extra
    (fymo[clerk]); ClerkProvider.__init__ already refused to build this closure
    at all if `_pyjwt_available()` was False, so the ImportError branch below
    is defense in depth for a partial/corrupted install rather than the
    primary guard: it should not be reachable in the normal missing-extra
    case, that fails earlier and louder, at boot."""

    def verify(token: str) -> Optional[dict]:
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError as e:  # pragma: no cover - _pyjwt_available already guards this
            raise RuntimeError(
                f"Clerk token verification needs the 'pyjwt[crypto]' package. Install it with: {_INSTALL_HINT}"
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
