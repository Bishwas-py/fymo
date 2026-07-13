"""fymo_uid cookie management.

The uid is an opaque identity token used to dedupe reactions, attribute
anonymous comments, etc. It is NOT an authentication credential on its own,
but the value IS HMAC-signed by the server so that clients cannot forge a
specific uid by editing the cookie. App authors who want real authentication
should layer it on top (e.g. an additional signed `fymo_session` cookie).

Wire format on the cookie:
    fymo_uid=<uid>.<sig>
where:
    uid = "u_" + secrets.token_urlsafe(12)            # ~96 bits of entropy
    sig = base64url(hmac_sha256(secret, uid))[:22]   # ~128 bits of entropy

A cookie that is missing the dot, has a malformed signature, or fails HMAC
verification is treated as if no cookie were present — a fresh uid is issued.
"""
import base64
import hmac
import secrets
from hashlib import sha256
from http.cookies import SimpleCookie

_UID_COOKIE = "fymo_uid"
_TEN_YEARS_SECONDS = 10 * 365 * 24 * 60 * 60
_SIG_LEN = 22  # base64url chars; ~132 bits of HMAC truncation, plenty

# Set by FymoApp.__init__. Must be bytes. None means "not configured" — any
# call to _ensure_uid will raise so the misconfiguration is loud rather than
# silently issuing forgeable cookies.
_secret: bytes | None = None


def set_secret(secret: bytes) -> None:
    """Install the HMAC secret used to sign uid cookies. Called once per process."""
    global _secret
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < 16:
        raise ValueError("identity secret must be at least 16 bytes")
    _secret = bytes(secret)


def _sign(uid: str) -> str:
    if _secret is None:
        raise RuntimeError(
            "fymo identity secret not configured; create FymoApp first or "
            "call fymo.remote.identity.set_secret(b'...') in tests"
        )
    mac = hmac.new(_secret, uid.encode("utf-8"), sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")[:_SIG_LEN]


def _verify(token: str) -> str | None:
    """Parse '<uid>.<sig>'; return uid if HMAC verifies, else None."""
    if "." not in token:
        return None
    uid, sig = token.rsplit(".", 1)
    if not uid.startswith("u_") or len(sig) != _SIG_LEN:
        return None
    expected = _sign(uid)
    if hmac.compare_digest(expected, sig):
        return uid
    return None


def _read_cookie(environ: dict, name: str) -> str | None:
    raw = environ.get("HTTP_COOKIE", "")
    if not raw:
        return None
    cookies = SimpleCookie()
    cookies.load(raw)
    morsel = cookies.get(name)
    return morsel.value if morsel else None


def _ensure_uid(environ: dict) -> tuple[str, str | None]:
    """Return (uid, Set-Cookie header value or None if no cookie needs to be set).

    The cookie is HttpOnly + SameSite=Lax always. Adds Secure when the request
    arrived over https, so the cookie is only sent back over TLS. Production
    deployments behind a reverse proxy must propagate the original scheme via
    `wsgi.url_scheme` (gunicorn does this from `X-Forwarded-Proto` when
    configured with `--forwarded-allow-ips`).
    """
    existing = _read_cookie(environ, _UID_COOKIE)
    if existing is not None:
        verified = _verify(existing)
        if verified is not None:
            return verified, None
        # Tampered, unsigned, or stale-format cookie — fall through to reissue.
    new_uid = "u_" + secrets.token_urlsafe(12)
    signed = f"{new_uid}.{_sign(new_uid)}"
    parts = [
        f"{_UID_COOKIE}={signed}",
        "Path=/",
        f"Max-Age={_TEN_YEARS_SECONDS}",
        "SameSite=Lax",
        "HttpOnly",
    ]
    if environ.get("wsgi.url_scheme") == "https":
        parts.append("Secure")
    return new_uid, "; ".join(parts)


def current_uid() -> str:
    """Return the uid of the current remote-function request.
    Must be called from within a request_scope; raises otherwise."""
    from fymo.remote.context import _current_event
    event = _current_event.get()
    if event is None:
        raise RuntimeError("current_uid() called outside of a remote-function request scope")
    return event["uid"]
