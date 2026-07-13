"""Auth request-scope helpers: current_user(), @require_auth, and the
cookie-queue mechanism that lets signup/login/logout schedule Set-Cookie
headers without explicitly returning them to the WSGI layer.

current_user() reads `fymo_session` from the existing request scope's
cookies, verifies via session.verify_session_token, then looks up the
user via the active UserStore. Returns None if anything's missing or
malformed; callers use @require_auth to upgrade that to a 401 response.
"""
from __future__ import annotations

import contextvars
import functools
from typing import Callable, List, Optional, TypeVar

from fymo.auth.email import EmailSender, LoggingEmailSender
from fymo.auth.session import build_set_cookie, build_clear_cookie, verify_session_token
from fymo.auth.store import User, UserStore


# Mutable list of Set-Cookie header values queued by auth functions during
# a single request. Initialized in start_auth_scope(), drained by the
# router via consume_pending_cookies() once the function returns.
_pending_cookies: contextvars.ContextVar[Optional[List[str]]] = contextvars.ContextVar(
    "fymo_auth_pending_cookies", default=None
)

# Process-wide UserStore handle. Installed once by FymoApp.__init__ — the
# remote-function world has no FymoApp reference, so a module-level seam is
# how we get the store to current_user(). Same pattern we use for
# identity._secret and manifest_cache._SHARED_CACHE.
_user_store: Optional[UserStore] = None


def set_user_store(store: UserStore) -> None:
    global _user_store
    _user_store = store


def get_user_store() -> UserStore:
    if _user_store is None:
        raise RuntimeError(
            "auth UserStore not configured; FymoApp must initialize with auth.enabled=true"
        )
    return _user_store


# Process-wide EmailSender handle, same seam pattern as _user_store above.
# Unlike the store, this one always has a working default (LoggingEmailSender)
# so email-verification works out of the box with no SMTP configuration —
# apps override it via `auth.email_sender` in fymo.yml when they want real
# delivery.
_email_sender: EmailSender = LoggingEmailSender()


def set_email_sender(sender: EmailSender) -> None:
    global _email_sender
    _email_sender = sender


def get_email_sender() -> EmailSender:
    return _email_sender


# --------------- scope lifecycle (called by the router) ---------------


def start_auth_scope():
    """Begin a request scope for auth. Returns a token to reset with."""
    return _pending_cookies.set([])


def end_auth_scope(token) -> None:
    _pending_cookies.reset(token)


def consume_pending_cookies() -> List[str]:
    """Drain queued Set-Cookie values. Safe to call when no scope is active."""
    pending = _pending_cookies.get()
    if pending is None:
        return []
    return list(pending)


def _queue_set_cookie(value: str) -> None:
    pending = _pending_cookies.get()
    if pending is not None:
        pending.append(value)


# --------------- session ops, called from signup/login/logout ---------------


def queue_session_cookie(user_id: int, epoch: int, *, environ: dict, max_age: Optional[int] = None) -> None:
    """Schedule a `fymo_session` Set-Cookie for this response."""
    from fymo.auth.session import make_session_token
    token = make_session_token(user_id, epoch)
    kwargs = {"environ": environ}
    if max_age is not None:
        kwargs["max_age"] = max_age
    _queue_set_cookie(build_set_cookie(token, **kwargs))


def queue_session_clear(environ: dict) -> None:
    _queue_set_cookie(build_clear_cookie(environ=environ))


# --------------- public helpers used by app authors ---------------


# --------------- session resolver chain (identity resolution) ---------------
#
# A resolver maps a request event -> User | None. current_user() walks the
# built-in fymo-session resolver first, then any a provider registered, and
# returns the first non-None. This is the Axis-B seam: token/JWT providers
# (e.g. Clerk) resolve identity without a fymo session by registering here.

SessionResolver = Callable[[dict], Optional[User]]

_session_resolvers: List[SessionResolver] = []


def register_session_resolver(resolver: SessionResolver) -> None:
    """Add a provider resolver, tried after the built-in fymo-session cookie."""
    _session_resolvers.append(resolver)


def reset_session_resolvers() -> None:
    """Drop all registered provider resolvers (re-init / tests)."""
    _session_resolvers.clear()


def _fymo_session_resolver(event: dict) -> Optional[User]:
    """Built-in resolver: validate the signed `fymo_session` cookie.

    Missing cookie, bad signature, expiry, deleted user, or a stale epoch
    (post logout / password change) all collapse to None.
    """
    raw = event.get("cookies", {}).get("fymo_session")
    if not raw:
        return None
    verified = verify_session_token(raw)
    if verified is None:
        return None
    user_id, epoch = verified
    user = get_user_store().get_by_id(user_id)
    if user is None or user.session_epoch != epoch:
        return None
    return user


def current_user() -> Optional[User]:
    """Return the authenticated user, or None when no provider recognizes the
    request. Walks the fymo-session cookie first, then provider resolvers."""
    from fymo.remote.context import _current_event
    event = _current_event.get()
    if event is None:
        raise RuntimeError(
            "current_user() called outside of a remote-function request scope"
        )
    for resolve in (_fymo_session_resolver, *_session_resolvers):
        user = resolve(event)
        if user is not None:
            return user
    return None


F = TypeVar("F", bound=Callable)


def require_auth(fn: F) -> F:
    """Decorator: 401 envelope when no authenticated user is present.

    Raises AuthRequired (a RemoteError subclass), which the remote router
    already serializes to {type: "error", status: 401, error: "unauthenticated"}.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            raise AuthRequired()
        return fn(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


# --------------- error type ---------------


from fymo.remote.errors import RemoteError  # noqa: E402 — must come after wrapper


class AuthRequired(RemoteError):
    """Raised by @require_auth when there's no valid session."""
    def __init__(self, message: str = "authentication required"):
        super().__init__(message, status=401, code="unauthenticated")
