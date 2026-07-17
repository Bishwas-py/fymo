"""Request-scoped context for remote functions, using contextvars (thread/coroutine safe)."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_current_event: ContextVar[dict | None] = ContextVar("_current_event", default=None)

# Whether X-Forwarded-Proto should be trusted when resolving the request
# scheme (used for the session cookie's Secure flag). Same trust boundary as
# RateLimitConfig.trust_proxy / X-Forwarded-For: only safe behind a reverse
# proxy that overwrites the header. Installed once by FymoApp.__init__ from
# middleware.rate_limit_config.trust_proxy — the remote-function world has no
# FymoApp reference, so a module-level seam is how the flag gets here. Same
# pattern as identity._secret.
_trust_proxy: bool = False


def set_trust_proxy(value: bool) -> None:
    global _trust_proxy
    _trust_proxy = bool(value)


@dataclass(frozen=True)
class RequestEvent:
    uid: str
    remote_addr: str
    cookies: dict[str, str]
    headers: dict[str, str]


def request_event() -> RequestEvent:
    """Return the current RequestEvent. Raises if called outside a request scope."""
    ev = _current_event.get()
    if ev is None:
        raise RuntimeError("request_event() called outside of a remote-function request scope")
    return RequestEvent(
        uid=ev["uid"],
        remote_addr=ev.get("remote_addr", ""),
        cookies=ev.get("cookies", {}),
        headers=ev.get("headers", {}),
    )


@contextmanager
def request_scope(uid: str, environ: dict):
    """Push a request scope onto the contextvar for the duration of a remote call."""
    headers = {k[5:].replace("_", "-").lower(): v for k, v in environ.items() if k.startswith("HTTP_")}
    cookies: dict[str, str] = {}
    if environ.get("HTTP_COOKIE"):
        from http.cookies import SimpleCookie
        c = SimpleCookie()
        c.load(environ["HTTP_COOKIE"])
        cookies = {k: v.value for k, v in c.items()}
    from fymo.core.middleware import resolve_scheme

    payload = {
        "uid": uid,
        "remote_addr": environ.get("REMOTE_ADDR", ""),
        "cookies": cookies,
        "headers": headers,
        "scheme": resolve_scheme(environ, _trust_proxy),
    }
    # Identity resolution that ran before this scope opened (rate-limit key
    # resolution) caches its outcome on the environ; seed the event cache
    # from it so current_uid() does not re-run the resolver chain.
    from fymo.auth.identity import ENVIRON_RESOLUTION_KEY, _RESOLUTION_KEY
    if ENVIRON_RESOLUTION_KEY in environ:
        payload[_RESOLUTION_KEY] = environ[ENVIRON_RESOLUTION_KEY]
    token = _current_event.set(payload)
    try:
        yield
    finally:
        _current_event.reset(token)
