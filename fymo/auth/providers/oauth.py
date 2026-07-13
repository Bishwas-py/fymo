"""Shared OAuth 2.0 Authorization-Code + PKCE machinery.

Concrete providers (Google, generic OIDC, Auth0) supply only endpoint URLs,
scopes, and a `userinfo -> (sub, email)` mapping — the whole redirect/callback
dance lives here once. State and the PKCE verifier are signed with FYMO_SECRET
and carried in the `state` param, so there's no server-side store and callback
CSRF is covered by the signature.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from fymo.auth.context import get_user_store
from fymo.auth.providers.base import BaseProvider, HttpRoute
from fymo.auth.session import build_set_cookie, make_session_token
from fymo.auth.store import User, UserStore

_SIG_LEN = 22


def _secret() -> bytes:
    from fymo.remote import identity
    if identity._secret is None:
        raise RuntimeError("fymo identity secret not configured before OAuth use")
    return identity._secret


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _sign_state(payload: dict) -> str:
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())[:_SIG_LEN]
    return f"{body}.{sig}"


def _verify_state(state: str) -> Optional[dict]:
    if not state or "." not in state:
        return None
    body, sig = state.rsplit(".", 1)
    expected = _b64url(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())[:_SIG_LEN]
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        return None


def _pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _safe_next(path: Optional[str]) -> str:
    """Clamp the post-login redirect to a same-site relative path. Absolute
    URLs and protocol-relative forms (`//host`, `/\\host`) are browser-off-site,
    so they collapse to `/` — no open redirect."""
    if not path or not path.startswith("/") or path.startswith(("//", "/\\")):
        return "/"
    return path


def resolve_or_create_user(
    store: UserStore,
    provider: str,
    sub: str,
    email: Optional[str],
    email_verified: bool = False,
) -> User:
    """Find the user behind an external identity, else match by *verified* email,
    else create one — then link. The single place account linking happens.

    The email is only trusted for matching/creating when the IdP asserts it is
    verified. An unverified email must never merge into an existing account,
    otherwise an attacker who registers a victim's address at any IdP could take
    over the victim's account (classic OAuth linking flaw). Unverified logins get
    a provider-scoped identity of their own.
    """
    user = store.get_by_identity(provider, sub)
    if user is not None:
        return user

    trusted_email = email if (email and email_verified) else None
    if trusted_email:
        user = store.get_by_email(trusted_email)
    if user is None:
        # No password — this account authenticates through the provider.
        user = store.create(email=trusted_email or f"{provider}:{sub}", password_hash=None)
    store.link_identity(user.id, provider, sub, email)
    return user


class _UrllibTransport:
    """Default HTTP transport. Injected with a fake in tests."""

    def post_form(self, url: str, fields: Dict[str, str]) -> dict:
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(url, data=data, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - fixed provider URLs
            return json.loads(r.read())

    def get_json(self, url: str, bearer: str) -> dict:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            return json.loads(r.read())


def _respond(start_response, status: str, location: str, set_cookie: Optional[str] = None):
    headers = [("Location", location), ("Content-Length", "0")]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    start_response(status, headers)
    return [b""]


def _error(start_response, status: str, message: str):
    body = message.encode("utf-8")
    start_response(status, [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


class OAuthProvider(BaseProvider):
    """Base for Authorization-Code providers. Subclasses set the endpoints."""

    authorize_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    scopes: str = "openid email"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        transport=None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = transport or _UrllibTransport()

    @classmethod
    def from_config(cls, opts: dict) -> "OAuthProvider":
        """Build from fymo.yml. Secrets come from env (client_id_env /
        client_secret_env); redirect_uri is the absolute callback URL."""
        import os
        return cls(
            client_id=os.environ.get(opts.get("client_id_env", ""), ""),
            client_secret=os.environ.get(opts.get("client_secret_env", ""), ""),
            redirect_uri=opts.get("redirect_uri", f"/auth/{cls.id}/callback"),
        )

    # Subclasses map the provider's userinfo payload to (sub, email).
    def map_userinfo(self, info: dict) -> Tuple[str, Optional[str]]:
        raise NotImplementedError

    def http_routes(self) -> List[HttpRoute]:
        return [
            HttpRoute("GET", f"/auth/{self.id}/start", self._start),
            HttpRoute("GET", f"/auth/{self.id}/callback", self._callback),
        ]

    def _start(self, environ, start_response):
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        next_path = query.get("next", ["/"])[0]
        verifier, challenge = _pkce_pair()
        state = _sign_state({"v": verifier, "n": secrets.token_urlsafe(12), "next": next_path})
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        location = f"{self.authorize_endpoint}?{urllib.parse.urlencode(params)}"
        return _respond(start_response, "302 FOUND", location)

    def _callback(self, environ, start_response):
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        code = query.get("code", [""])[0]
        state = query.get("state", [""])[0]
        data = _verify_state(state)
        if not code or data is None:
            return _error(start_response, "400 BAD REQUEST", "invalid oauth callback")

        # Wrap the IdP round-trips so a transport error surfaces as a clean 502
        # rather than a 500 whose traceback could echo the request.
        try:
            tokens = self._http.post_form(
                self.token_endpoint,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": data["v"],
                },
            )
            access_token = tokens.get("access_token")
            if not access_token:
                return _error(start_response, "502 BAD GATEWAY", "token exchange failed")
            info = self._http.get_json(self.userinfo_endpoint, access_token)
        except Exception:
            return _error(start_response, "502 BAD GATEWAY", "identity provider error")
        sub, email = self.map_userinfo(info)
        if not sub:
            return _error(start_response, "502 BAD GATEWAY", "no subject in userinfo")

        email_verified = bool(info.get("email_verified"))
        user = resolve_or_create_user(
            get_user_store(), self.id, str(sub), email, email_verified
        )
        token = make_session_token(user.id, user.session_epoch)
        cookie = build_set_cookie(token, environ=environ)
        return _respond(
            start_response, "302 FOUND", _safe_next(data.get("next")), set_cookie=cookie
        )


class GoogleProvider(OAuthProvider):
    id = "google"
    authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    userinfo_endpoint = "https://openidconnect.googleapis.com/v1/userinfo"
    scopes = "openid email profile"

    def map_userinfo(self, info: dict) -> Tuple[str, Optional[str]]:
        return info.get("sub", ""), info.get("email")


class OIDCProvider(OAuthProvider):
    """Generic OIDC / OAuth2 provider configured entirely from fymo.yml.

    Covers Auth0, Okta, GitHub, or any Authorization-Code IdP — supply the
    endpoint URLs, an id, and which userinfo fields carry the subject + email.
    """

    def __init__(
        self,
        *,
        id: str,
        authorize_endpoint: str,
        token_endpoint: str,
        userinfo_endpoint: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str = "openid email profile",
        sub_field: str = "sub",
        email_field: str = "email",
        transport=None,
    ):
        super().__init__(
            client_id=client_id, client_secret=client_secret,
            redirect_uri=redirect_uri, transport=transport,
        )
        self.id = id
        self.authorize_endpoint = authorize_endpoint
        self.token_endpoint = token_endpoint
        self.userinfo_endpoint = userinfo_endpoint
        self.scopes = scopes
        self._sub_field = sub_field
        self._email_field = email_field

    @classmethod
    def from_config(cls, opts: dict) -> "OIDCProvider":
        import os

        def secret(key: str) -> str:
            env = opts.get(f"{key}_env")
            return os.environ.get(env, "") if env else opts.get(key, "")

        return cls(
            id=opts["id"],
            authorize_endpoint=opts["authorize_endpoint"],
            token_endpoint=opts["token_endpoint"],
            userinfo_endpoint=opts["userinfo_endpoint"],
            client_id=secret("client_id"),
            client_secret=secret("client_secret"),
            redirect_uri=opts.get("redirect_uri", f"/auth/{opts['id']}/callback"),
            scopes=opts.get("scopes", "openid email profile"),
            sub_field=opts.get("sub_field", "sub"),
            email_field=opts.get("email_field", "email"),
        )

    def map_userinfo(self, info: dict) -> Tuple[str, Optional[str]]:
        return info.get(self._sub_field, ""), info.get(self._email_field)
