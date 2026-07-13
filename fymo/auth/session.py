"""Signed `fymo_session` cookie carrying the authenticated user_id.

Wire format: `fymo_session=<user_id>.<issued_at>.<epoch>.<sig>` where sig =
base64url-truncated HMAC-SHA256 of `f"sess:{user_id}:{issued_at}:{epoch}"`
under the same FYMO_SECRET that signs `fymo_uid`. The "sess:" prefix
prevents cross-context forgery (a valid `fymo_uid` signature can't be reused
as a session signature).

Two values give the token a lifetime and a revocation handle:

  * `issued_at` (unix seconds) — `verify_session_token` rejects tokens older
    than `max_age`, so a captured token does not work forever.
  * `epoch` — the user's `session_epoch` at issue time. It is signed but NOT
    checked here (this module has no store); the caller compares it against
    the user's current epoch. Bumping the epoch (logout, password change)
    invalidates every token minted under the previous value.

Tampering, malformed tokens, expiry, and unknown user_ids all collapse to
the same "no session" answer; callers can't distinguish via response shape.
"""
from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256
from http.cookies import SimpleCookie
from typing import Optional, Tuple

_SESSION_COOKIE = "fymo_session"
_SIG_LEN = 22
_DEFAULT_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def _get_secret() -> bytes:
    """Look up the live secret each call so set_secret() updates take effect."""
    from fymo.remote import identity
    if identity._secret is None:
        raise RuntimeError(
            "fymo identity secret not configured; FymoApp must initialize before sessions"
        )
    return identity._secret


def _sign(user_id: int, issued_at: int, epoch: int) -> str:
    payload = f"sess:{user_id}:{issued_at}:{epoch}".encode("utf-8")
    mac = hmac.new(_get_secret(), payload, sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")[:_SIG_LEN]


def make_session_token(user_id: int, epoch: int, *, issued_at: Optional[int] = None) -> str:
    """Encode a session token binding `user_id` to `epoch` at `issued_at`."""
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive int")
    if not isinstance(epoch, int) or epoch < 0:
        raise ValueError("epoch must be a non-negative int")
    if issued_at is None:
        issued_at = int(time.time())
    return f"{user_id}.{issued_at}.{epoch}.{_sign(user_id, issued_at, epoch)}"


def verify_session_token(
    token: str, *, max_age: int = _DEFAULT_MAX_AGE, now: Optional[int] = None
) -> Optional[Tuple[int, int]]:
    """Return `(user_id, epoch)` if `token` is well-formed, signature-valid, and
    unexpired, else None. Epoch revocation is enforced by the caller."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    uid_str, issued_str, epoch_str, sig = parts
    if len(sig) != _SIG_LEN:
        return None
    try:
        user_id = int(uid_str)
        issued_at = int(issued_str)
        epoch = int(epoch_str)
    except ValueError:
        return None
    if user_id <= 0 or epoch < 0 or issued_at <= 0:
        return None
    expected = _sign(user_id, issued_at, epoch)
    if not hmac.compare_digest(expected, sig):
        return None
    if now is None:
        now = int(time.time())
    if now - issued_at > max_age:
        return None
    return user_id, epoch


def read_session_cookie(environ: dict) -> Optional[Tuple[int, int]]:
    raw = environ.get("HTTP_COOKIE", "")
    if not raw:
        return None
    cookies = SimpleCookie()
    cookies.load(raw)
    morsel = cookies.get(_SESSION_COOKIE)
    if morsel is None:
        return None
    return verify_session_token(morsel.value)


def build_set_cookie(token: str, *, environ: dict, max_age: int = _DEFAULT_MAX_AGE) -> str:
    # `environ["wsgi.url_scheme"]` here is the *resolved* scheme, not
    # necessarily the raw socket scheme: callers behind a TLS-terminating
    # proxy (e.g. fymo.remote.context.request_scope, gated on trust_proxy)
    # already fold X-Forwarded-Proto into this value before it gets here, so
    # a single check below covers both direct-https and proxied-https.
    parts = [
        f"{_SESSION_COOKIE}={token}",
        "Path=/",
        f"Max-Age={max_age}",
        "SameSite=Lax",
        "HttpOnly",
    ]
    if environ.get("wsgi.url_scheme") == "https":
        parts.append("Secure")
    return "; ".join(parts)


def build_clear_cookie(*, environ: dict) -> str:
    """Set-Cookie that expires the session immediately. Returned on logout.

    See `build_set_cookie` for the note on `wsgi.url_scheme` reflecting the
    resolved (proxy-aware) scheme, not necessarily the raw socket scheme.
    """
    parts = [
        f"{_SESSION_COOKIE}=",
        "Path=/",
        "Max-Age=0",
        "SameSite=Lax",
        "HttpOnly",
    ]
    if environ.get("wsgi.url_scheme") == "https":
        parts.append("Secure")
    return "; ".join(parts)
