"""fymo_uid cookie management. The uid is an opaque identity token,
NOT a credential — used to dedupe reactions, attribute comments, etc."""
import secrets
from http.cookies import SimpleCookie

_UID_COOKIE = "fymo_uid"
_TEN_YEARS_SECONDS = 10 * 365 * 24 * 60 * 60


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
    if existing:
        return existing, None
    new_uid = "u_" + secrets.token_urlsafe(12)
    parts = [
        f"{_UID_COOKIE}={new_uid}",
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
