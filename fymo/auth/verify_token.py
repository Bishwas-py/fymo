"""Signed single-use tokens: `<user_id>.<issued_at>.<sig>`.

Mirrors `fymo/auth/session.py`'s HMAC pattern (same `FYMO_SECRET`, same
base64url-truncated HMAC-SHA256 signature) but each purpose signs its own
prefix ("verify:" for email verification, "reset:" for password reset) so a
token minted for one purpose can never be replayed as the other — the prefix
is part of the signed payload, so swapping it invalidates the signature.

Signature + expiry alone would make a token stateless and replayable forever
within its window. The store's `consume_*_token` methods add single-use on
top: they store `hash_token(token)` on the user row and clear it the moment
the token is consumed, so a captured/replayed link stops working after the
first successful use (or after a newer token replaces it via a fresh
request).
"""
from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256
from typing import Optional, Tuple

from fymo.auth.session import _get_secret

_SIG_LEN = 22
_DEFAULT_MAX_AGE = 24 * 60 * 60  # 24 hours


def _sign(prefix: str, user_id: int, issued_at: int) -> str:
    payload = f"{prefix}:{user_id}:{issued_at}".encode("utf-8")
    mac = hmac.new(_get_secret(), payload, sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")[:_SIG_LEN]


def _make_token(prefix: str, user_id: int, *, issued_at: Optional[int] = None) -> str:
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive int")
    if issued_at is None:
        issued_at = int(time.time())
    return f"{user_id}.{issued_at}.{_sign(prefix, user_id, issued_at)}"


def _verify_token(
    prefix: str, token: str, *, max_age: int = _DEFAULT_MAX_AGE, now: Optional[int] = None
) -> Optional[Tuple[int, int]]:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    uid_str, issued_str, sig = parts
    if len(sig) != _SIG_LEN:
        return None
    try:
        user_id = int(uid_str)
        issued_at = int(issued_str)
    except ValueError:
        return None
    if user_id <= 0 or issued_at <= 0:
        return None
    expected = _sign(prefix, user_id, issued_at)
    if not hmac.compare_digest(expected, sig):
        return None
    if now is None:
        now = int(time.time())
    if now - issued_at > max_age:
        return None
    return user_id, issued_at


def make_verify_token(user_id: int, *, issued_at: Optional[int] = None) -> str:
    """Encode an email-verification token binding `user_id` at `issued_at`."""
    return _make_token("verify", user_id, issued_at=issued_at)


def verify_verify_token(
    token: str, *, max_age: int = _DEFAULT_MAX_AGE, now: Optional[int] = None
) -> Optional[Tuple[int, int]]:
    """Return `(user_id, issued_at)` if `token` is well-formed, signature-valid,
    and unexpired, else None. Single-use is enforced by the caller (the store),
    not here — this function only checks the token's own integrity."""
    return _verify_token("verify", token, max_age=max_age, now=now)


def make_reset_token(user_id: int, *, issued_at: Optional[int] = None) -> str:
    """Encode a password-reset token binding `user_id` at `issued_at`.

    Uses a distinct "reset:" prefix (see module docstring) so an email
    verification token can never be replayed here, and vice versa.
    """
    return _make_token("reset", user_id, issued_at=issued_at)


def verify_reset_token(
    token: str, *, max_age: int = _DEFAULT_MAX_AGE, now: Optional[int] = None
) -> Optional[Tuple[int, int]]:
    """Return `(user_id, issued_at)` if `token` is well-formed, signature-valid,
    and unexpired, else None. Single-use is enforced by the caller (the store),
    not here — this function only checks the token's own integrity."""
    return _verify_token("reset", token, max_age=max_age, now=now)


def hash_token(token: str) -> str:
    """One-way digest stored on the user row so the raw token never sits at
    rest in the DB — only its hash, which is compared on consume."""
    return sha256(token.encode("utf-8")).hexdigest()
