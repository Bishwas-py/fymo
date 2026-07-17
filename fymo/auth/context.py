"""Auth request-scope helpers: @require_auth, identity extras, and the
cookie-queue mechanism that lets app auth code schedule Set-Cookie headers
without explicitly returning them to the WSGI layer.

@require_auth reads current_uid() (the @identify resolver chain, see
fymo.auth.identity) and raises AuthRequired for anonymous requests; the
remote router serializes that to the standard 401 envelope.
"""
from __future__ import annotations

import contextvars
import functools
from types import MappingProxyType
from typing import Callable, List, Mapping, Optional, TypeVar

from fymo.auth.identity import current_uid


# Mutable list of Set-Cookie header values queued during a single request.
# Initialized in start_auth_scope(), appended to by fymo.remote.cookies'
# set_cookie()/clear_cookie(), drained by the router via
# consume_pending_cookies() once the function returns.
_pending_cookies: contextvars.ContextVar[Optional[List[str]]] = contextvars.ContextVar(
    "fymo_auth_pending_cookies", default=None
)


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


# --------------- identity extras (app-defined data next to the identity) ---
#
# fymo answers "who is this"; apps also need "what may this user do", and
# that data (org, roles, scopes, tenant) has to live somewhere reachable
# wherever current_uid() is. Hooks registered here run once per request
# scope, right after the resolver chain returns a uid, and their merged
# result is stored on the mutable per-request event dict that
# _current_event holds. fymo stores the value and never inspects it.
#
# A hook (rather than an imperative setter) is the population point because
# resolution happens inside current_uid(), framework code: apps would
# otherwise have no code of their own that executes at resolution time.
# The hook fires no matter which resolver in the chain won.
#
# Coverage matches current_uid() exactly: remote functions, SSR
# controllers/layouts and the soft-nav data endpoint, and broadcast guards.

IdentityExtrasHook = Callable[[str], Mapping[str, object]]

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
    """Add a hook called once per request scope with the resolved uid string.

    Hooks run in registration order the first time current_uid() resolves
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

    Empty until current_uid() first resolves a uid in this scope (or when
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


def _populate_identity_extras(event: dict, uid: str) -> None:
    """Run the hooks once for this scope with the resolved uid string."""
    if _EXTRAS_KEY in event or not _identity_extras_hooks:
        return
    merged: dict = {}
    for hook in _identity_extras_hooks:
        merged.update(hook(uid))
    event[_EXTRAS_KEY] = MappingProxyType(merged)


F = TypeVar("F", bound=Callable)


def require_auth(fn: F) -> F:
    """Decorator: 401 envelope when no resolver identifies the request.

    Raises AuthRequired (a RemoteError subclass), which the remote router
    already serializes to {type: "error", status: 401, error: "unauthenticated"}
    and points at the signin route when the app has one.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if current_uid() is None:
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
    """Raised by @require_auth when no resolver identifies the request."""
    def __init__(self, message: str = "authentication required"):
        super().__init__(message, status=401, code="unauthenticated")
