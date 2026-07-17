"""Identity resolvers (issue #80): mechanism, not model.

Identity is an opaque `uid` string produced by app-defined resolvers.
Apps register resolvers with @identify; current_uid() walks the chain
inside a request scope and returns the first non-None Identity's uid,
or None for anonymous requests. The framework owns no user shape and
no user table; mapping a uid to a row is app code.

This surface coexists with the legacy User/UserStore world during the
migration: current_uid() never consults the legacy session-resolver
chain, and current_user() never consults this one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional


@dataclass(frozen=True)
class Identity:
    """An authenticated identity: a single opaque, stable, app-defined uid.

    Everything else about the user (email, roles, org) is app data,
    reachable via identity_extras() or the app's own store.
    """
    uid: str


@dataclass(frozen=True)
class ResolverEvent:
    """The request view passed to identity resolvers.

    This is the frozen, versioned public contract for identity resolvers
    (issue #80 section 9): external resolver packages depend on exactly
    these fields, so the shape only grows additively, never mutates.
    It is a narrow view of the request, not the whole request object,
    to keep the coupling surface small.
    """
    remote_addr: str
    cookies: Mapping[str, str]
    headers: Mapping[str, str]
    scheme: str


IdentityResolver = Callable[[ResolverEvent], Optional[Identity]]

_identity_resolvers: List[IdentityResolver] = []

# Cache key on the mutable per-request event dict; present means resolution
# already ran this scope (value may be None for anonymous).
_RESOLUTION_KEY = "identity_resolution"

# WSGI-environ mirror of _RESOLUTION_KEY for resolution that runs before the
# request scope opens (rate-limit key resolution, fymo/remote/rate_limit.py):
# a clean pre-scope walk caches its outcome here, and request_scope
# (fymo/remote/context.py) seeds the event cache from it, so resolvers still
# run at most once per request.
ENVIRON_RESOLUTION_KEY = "fymo.identity_resolution"


def _resolver_registration_key(fn: IdentityResolver):
    """Identity of a resolver's definition site, stable across importlib.reload.

    The dev process re-executes app module bodies several times per reload
    (hygiene check, guarded-sites scan, discovery), and each reload creates
    a new function object, so object identity cannot dedup a top-level
    registration. The (module, qualname, file, line) of the definition
    survives reloads; two distinct lambdas in one scope still differ by
    line. Callables without __code__ fall back to object identity."""
    code = getattr(fn, "__code__", None)
    if code is None:
        return fn
    return (
        getattr(fn, "__module__", None),
        getattr(fn, "__qualname__", None),
        code.co_filename,
        code.co_firstlineno,
    )


def identify(fn: IdentityResolver) -> IdentityResolver:
    """Register `fn` as an identity resolver: (ResolverEvent) -> Identity | None.

    Resolvers run in registration order; the first non-None Identity wins.
    Registering a resolver whose definition site is already registered
    replaces the stale entry in place (keeping order) instead of appending,
    so the natural registration point, the top level of an app module,
    stays idempotent under the dev server's module reloads.

    Because dedup keys on the definition site, factory-produced resolvers
    registered in a loop all share one site and collapse to a single
    registration (the last one). Register one function per definition site;
    a loop over identify(make_resolver(x)) will not do what it looks like."""
    key = _resolver_registration_key(fn)
    for i, existing in enumerate(_identity_resolvers):
        if _resolver_registration_key(existing) == key:
            _identity_resolvers[i] = fn
            return fn
    _identity_resolvers.append(fn)
    return fn


def reset_identity_resolvers() -> None:
    """Drop all registered identity resolvers (re-init / tests)."""
    _identity_resolvers.clear()


def registered_identity_resolvers() -> tuple:
    """Snapshot of the registered resolver chain, in registration order.

    Public accessor for build-time checks (fymo/build/hygiene.py) and
    diagnostics; the live list stays private."""
    return tuple(_identity_resolvers)


def current_uid() -> Optional[str]:
    """Return the current request's resolved uid, or None when anonymous.

    Walks the @identify chain at most once per request scope; the outcome
    (including the anonymous one) is cached on the request event. Raises
    the same RuntimeError as request_event() outside a scope."""
    from fymo.remote.context import _current_event
    event = _current_event.get()
    if event is None:
        raise RuntimeError(
            "current_uid() called outside of a remote-function request scope"
        )
    if _RESOLUTION_KEY in event:
        uid = event[_RESOLUTION_KEY]
        if uid is not None:
            # The resolution may have been seeded from a walk that ran
            # before this scope opened (the rate limiter caches its clean
            # walk on the environ), so the hooks have not fired yet here.
            # _populate_identity_extras is a no-op once extras exist.
            from fymo.auth.context import _populate_identity_extras
            _populate_identity_extras(event, uid)
        return uid
    resolver_event = ResolverEvent(
        remote_addr=event.get("remote_addr", ""),
        cookies=event.get("cookies", {}),
        headers=event.get("headers", {}),
        scheme=event.get("scheme", ""),
    )
    uid: Optional[str] = None
    for resolve in _identity_resolvers:
        ident = resolve(resolver_event)
        if ident is None:
            continue
        if not isinstance(ident, Identity):
            name = (
                f"{getattr(resolve, '__module__', '?')}."
                f"{getattr(resolve, '__qualname__', repr(resolve))}"
            )
            raise TypeError(
                f"identity resolver {name} returned {type(ident).__name__}; "
                "resolvers must return fymo.auth.Identity(uid=...) or None"
            )
        uid = ident.uid
        break
    event[_RESOLUTION_KEY] = uid
    if uid is not None:
        # Fire the identity-extras hooks with the resolved uid as the
        # subject, so app code (e.g. a generated app/auth/extras.py) can
        # attach its user row to the scope. Same hooks the legacy
        # current_user() walk fires with a User; on this path the subject
        # is the uid string. fymo stores the merged result, never reads it.
        from fymo.auth.context import _populate_identity_extras
        _populate_identity_extras(event, uid)
    return uid
