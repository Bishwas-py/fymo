"""Password hashing — stdlib hashlib.scrypt, zero external deps.

Encoded format: `scrypt$N$r$p$salt_b64$hash_b64`. All four params land in the
stored string so we can rotate them per row without losing the ability to
verify old passwords.

Verification is constant-time via hmac.compare_digest.

Why scrypt vs argon2id? Argon2id is the modern recommendation but lives
outside stdlib. fymo's opinion is "zero deps for core auth"; if your threat
model requires argon2id, swap the PasswordHasher Protocol later. scrypt
remains NIST-blessed (SP 800-63B) and is fine for any realistic web app.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


# Conservative defaults. Each password costs ~50ms to verify on a modern
# laptop — slow enough to make brute-force expensive, fast enough that login
# isn't user-visible. Tuned for login rate limiting (PR 1 middleware) to be
# the actual brute-force defense.
_DEFAULT_N = 2 ** 14  # 16384, the libsodium default
_DEFAULT_R = 8
_DEFAULT_P = 1
_SALT_BYTES = 16
_HASH_BYTES = 32


def hash_password(plaintext: str) -> str:
    """Hash a password. Returns an encoded string suitable for DB storage."""
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        plaintext.encode("utf-8"),
        salt=salt,
        n=_DEFAULT_N,
        r=_DEFAULT_R,
        p=_DEFAULT_P,
        dklen=_HASH_BYTES,
    )
    return _encode(_DEFAULT_N, _DEFAULT_R, _DEFAULT_P, salt, derived)


def verify_password(plaintext: str, stored: str) -> bool:
    """Constant-time compare. Returns False on any parse / shape mismatch."""
    if not isinstance(plaintext, str) or not plaintext:
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = _b64_decode(parts[4])
        expected = _b64_decode(parts[5])
    except (ValueError, base64.binascii.Error):
        return False

    try:
        derived = hashlib.scrypt(
            plaintext.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)


def _encode(n: int, r: int, p: int, salt: bytes, derived: bytes) -> str:
    return (
        "scrypt$"
        f"{n}${r}${p}$"
        f"{_b64_encode(salt)}${_b64_encode(derived)}"
    )


def _b64_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)
