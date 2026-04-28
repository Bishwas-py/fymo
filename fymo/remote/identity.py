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
    """Return (uid, Set-Cookie header value or None if no cookie needs to be set)."""
    existing = _read_cookie(environ, _UID_COOKIE)
    if existing:
        return existing, None
    new_uid = "u_" + secrets.token_urlsafe(12)
    cookie = (
        f"{_UID_COOKIE}={new_uid}; "
        f"Path=/; "
        f"Max-Age={_TEN_YEARS_SECONDS}; "
        f"SameSite=Lax; "
        f"HttpOnly"
    )
    return new_uid, cookie


def current_uid() -> str:
    """Return the uid of the current remote-function request.
    Must be called from within a request_scope; raises otherwise."""
    from fymo.remote.context import _current_event
    event = _current_event.get()
    if event is None:
        raise RuntimeError("current_uid() called outside of a remote-function request scope")
    return event["uid"]
