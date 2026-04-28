"""Request-scoped context for remote functions, using contextvars (thread/coroutine safe)."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_current_event: ContextVar[dict | None] = ContextVar("_current_event", default=None)


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
    payload = {
        "uid": uid,
        "remote_addr": environ.get("REMOTE_ADDR", ""),
        "cookies": cookies,
        "headers": headers,
    }
    token = _current_event.set(payload)
    try:
        yield
    finally:
        _current_event.reset(token)
