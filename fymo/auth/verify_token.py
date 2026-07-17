"""General-purpose signed uid tokens (issue #80): sign_token/verify_token.

The uid is an opaque string that may contain any character, including the
"." delimiter, so it is base64url-encoded into both the wire format and
the signed payload; no uid can smuggle a delimiter into either.

Wire format: `<b64url(uid)>.<issued_at>.<sig>` where sig is a
base64url-truncated HMAC-SHA256 (under FYMO_SECRET) of
`token:<b64url(uid)>:<issued_at>`. The "token:" prefix is part of the
signed payload, so a token minted here can never verify under another
HMAC purpose sharing the same secret (e.g. the fymo_uid identity cookie),
and vice versa.

Stateless by design: signature + expiry only. There is no single-use
enforcement here; add it in app code if the use case needs it.
"""
from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256
from typing import Optional

_SIG_LEN = 22
_DEFAULT_MAX_AGE = 24 * 60 * 60  # 24 hours


def _get_secret() -> bytes:
    """Look up the live secret each call so set_secret() updates take effect."""
    from fymo.remote import identity
    if identity._secret is None:
        raise RuntimeError(
            "fymo identity secret not configured; FymoApp must initialize before tokens"
        )
    return identity._secret


def _b64url_encode(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> Optional[str]:
    pad = "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s + pad).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _sign_uid(uid_b64: str, issued_at: int) -> str:
    payload = f"token:{uid_b64}:{issued_at}".encode("utf-8")
    mac = hmac.new(_get_secret(), payload, sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")[:_SIG_LEN]


def sign_token(uid: str, *, issued_at: Optional[int] = None) -> str:
    """Encode a general-purpose signed token binding `uid` at `issued_at`.

    Stateless: anyone holding FYMO_SECRET can verify it within its max_age
    window via verify_token(). There is no single-use enforcement here; add
    it in app code if the use case needs it."""
    if not isinstance(uid, str) or not uid:
        raise ValueError("uid must be a non-empty string")
    if issued_at is None:
        issued_at = int(time.time())
    uid_b64 = _b64url_encode(uid)
    return f"{uid_b64}.{issued_at}.{_sign_uid(uid_b64, issued_at)}"


def verify_token(
    token: str, *, max_age: int = _DEFAULT_MAX_AGE, now: Optional[int] = None
) -> Optional[str]:
    """Return the uid if `token` is well-formed, signature-valid, and
    unexpired, else None. Tampering, malformed tokens, and expiry all
    collapse to the same None."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    uid_b64, issued_str, sig = parts
    if len(sig) != _SIG_LEN:
        return None
    try:
        issued_at = int(issued_str)
    except ValueError:
        return None
    if issued_at <= 0:
        return None
    expected = _sign_uid(uid_b64, issued_at)
    if not hmac.compare_digest(expected, sig):
        return None
    if now is None:
        now = int(time.time())
    if now - issued_at > max_age:
        return None
    uid = _b64url_decode(uid_b64)
    if not uid:
        return None
    return uid
