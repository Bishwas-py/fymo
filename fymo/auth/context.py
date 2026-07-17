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
from types import MappingProxyType
from typing import Callable, List, Mapping, Optional, TypeVar

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


# --------------- identity extras (app-defined data next to the identity) ---
#
# fymo answers "who is this"; apps also need "what may this user do", and
# that data (org, roles, scopes, tenant) has to live somewhere reachable
# wherever current_user() is. Hooks registered here run once per request
# scope, right after a resolver returns a user, and their merged result is
# stored on the mutable per-request event dict that _current_event holds.
# fymo stores the value and never inspects it.
#
# A hook (rather than an imperative setter) is the population point because
# the built-in fymo-session resolver wins the chain before any registered
# resolver runs: apps on fymo's own sessions would otherwise have no code
# that executes at resolution time. The hook fires for every resolver in the
# chain equally, built-in or provider.
#
# Coverage matches current_user() exactly: remote functions, SSR
# controllers/layouts and the soft-nav data endpoint (both open the same
# request scope when auth is enabled, see fymo.core.ssr_controller), and
# broadcast guards.

IdentityExtrasHook = Callable[[User], Mapping[str, object]]

_identity_extras_hooks: List[IdentityExtrasHook] = []

_EXTRAS_KEY = "identity_extras"
_EMPTY_EXTRAS: Mapping[str, object] = MappingProxyType({})


def _hook_registration_key(hook: IdentityExtrasHook):
    """Identity of a hook's definition site, stable across importlib.reload.

    The dev process re-executes app module bodies several times per reload
    (hygiene check, guarded-sites scan, discovery), and each reload creates
    a new function object, so object identity cannot dedup a top-level
    registration. The (module, qualname, file, line) of the definition
    survives reloads; two distinct lambdas in one scope still differ by
    line. Callables without __code__ fall back to object identity."""
    code = getattr(hook, "__code__", None)
    if code is None:
        return hook
    return (
        getattr(hook, "__module__", None),
        getattr(hook, "__qualname__", None),
        code.co_filename,
        code.co_firstlineno,
    )


def register_identity_extras_hook(hook: IdentityExtrasHook) -> None:
    """Add a hook called once per request scope with the resolved User.

    Hooks run in registration order the first time current_user() resolves
    someone; their returned mappings are merged (later wins on key
    collision) and frozen for the rest of the scope. Never called for
    anonymous requests. During SSR a request scope is opened per controller
    invocation, so a hook runs once per getContext/getDoc call there, not
    once per HTTP request.

    Registering a hook whose definition site is already registered replaces
    the stale entry in place (keeping order) instead of appending, so the
    natural registration point, the top level of an app module, stays
    idempotent under the dev server's module reloads."""
    key = _hook_registration_key(hook)
    for i, existing in enumerate(_identity_extras_hooks):
        if _hook_registration_key(existing) == key:
            _identity_extras_hooks[i] = hook
            return
    _identity_extras_hooks.append(hook)


def reset_identity_extras_hooks() -> None:
    """Drop all registered hooks (re-init / tests)."""
    _identity_extras_hooks.clear()


def identity_extras() -> Mapping[str, object]:
    """Return the app-defined data attached to the resolved identity.

    Empty until current_user() first resolves a user in this scope (or when
    no hooks are registered); never an error inside a scope. Raises the same
    RuntimeError as request_event() outside one."""
    from fymo.remote.context import _current_event
    event = _current_event.get()
    if event is None:
        raise RuntimeError(
            "identity_extras() called outside of a remote-function request scope"
        )
    extras = event.get(_EXTRAS_KEY)
    if extras is None:
        return _EMPTY_EXTRAS
    return extras


def _populate_identity_extras(event: dict, subject) -> None:
    """Run the hooks once for this scope. `subject` is the resolved User on
    the legacy current_user() path and the resolved uid string on the new
    current_uid() path (fymo.auth.identity)."""
    if _EXTRAS_KEY in event or not _identity_extras_hooks:
        return
    merged: dict = {}
    for hook in _identity_extras_hooks:
        merged.update(hook(subject))
    event[_EXTRAS_KEY] = MappingProxyType(merged)


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
            _populate_identity_extras(event, user)
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
    # Marker attribute, same pattern as fymo.remote.decorators.remote's
    # __fymo_remote__. Lets build-time checks (see fymo.build.hygiene's
    # check_auth_enforcement_hygiene) find every @require_auth site without
    # re-deriving the answer from runtime behavior. functools.wraps already
    # copied fn.__dict__ onto wrapper, so this must be set after that call
    # to survive regardless of decorator stacking order with @remote.
    wrapper.__fymo_require_auth__ = True
    return wrapper  # type: ignore[return-value]


# --------------- error type ---------------


from fymo.remote.errors import RemoteError  # noqa: E402 — must come after wrapper


class AuthRequired(RemoteError):
    """Raised by @require_auth when there's no valid session."""
    def __init__(self, message: str = "authentication required"):
        super().__init__(message, status=401, code="unauthenticated")
