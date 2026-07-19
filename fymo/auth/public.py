"""The frontend identity boundary (issue #80): what the client may see.

Server-side identity is a uid plus whatever identity_extras() carries,
none of which auto-serializes. The one thing that crosses to the Svelte
layer is the output of the app's @public_identity projection, computed
per request and delivered as the `identity` slot: embedded in the SSR
HTML, carried on every soft-nav data response, and read by the generated
$auth client store.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from fymo.auth.identity import (
    Identity,
    current_uid,
    registered_identity_resolvers,
)

PublicIdentityProjection = Callable[[Identity], Mapping[str, object]]

_projection: Optional[PublicIdentityProjection] = None


def public_identity(fn: PublicIdentityProjection) -> PublicIdentityProjection:
    """Register `fn` as the app's public identity projection:
    (Identity) -> Mapping. Its output is the ONLY identity data serialized
    to the client (the $auth `identity` store); identity_extras() and
    everything else stay server-side.

    An app has exactly one projection; registering again replaces the
    previous one (last registration wins), which also keeps the natural
    registration point, the top level of an app/auth module, idempotent
    under the dev server's module reloads. Keep a single @public_identity
    function per app.

    Default when no projection is registered: a signed-in client sees
    {"uid": <uid>} and nothing else. The uid is the one field that is safe
    by construction (opaque, app-defined, and already inferable by the
    client from its own authenticated calls), so the default stays useful
    for the simple case without ever whitelisting data on the app's behalf.

    The projection runs server-side inside the request scope, so it may
    call identity_extras() to reach the app data attached to the identity.
    Return only a safe subset; anything returned here is embedded in every
    page's HTML for that signed-in user.
    """
    global _projection
    _projection = fn
    return fn


def reset_public_identity() -> None:
    """Drop the registered projection (re-init / tests)."""
    global _projection
    _projection = None


def registered_public_identity() -> Optional[PublicIdentityProjection]:
    """The registered projection, or None (build-time checks / diagnostics)."""
    return _projection


def project_identity() -> Optional[dict]:
    """Resolve the current request's identity and run the projection.

    Returns the projection output as a plain dict, or None when the
    request is anonymous. Must run inside a request scope (same
    requirement as current_uid())."""
    uid = current_uid()
    if uid is None:
        return None
    if _projection is None:
        return {"uid": uid}
    out = _projection(Identity(uid=uid))
    if not isinstance(out, Mapping):
        name = (
            f"{getattr(_projection, '__module__', '?')}."
            f"{getattr(_projection, '__qualname__', repr(_projection))}"
        )
        raise TypeError(
            f"public_identity projection {name} returned "
            f"{type(out).__name__}; projections must return a mapping of "
            "client-safe fields (e.g. {'uid': ident.uid})"
        )
    return dict(out)


def client_identity(environ: Optional[dict]) -> Optional[dict]:
    """The `identity` slot for a page-serving path (full-page SSR and the
    soft-nav data endpoint): resolve + project inside a short read-only
    request scope of its own.

    None (never a scope, never a resolver walk) when there is no request
    environ or no @identify resolvers are registered, so apps without the
    new identity chain pay nothing and serialize nothing."""
    if environ is None or not registered_identity_resolvers():
        return None
    from fymo.remote.context import request_scope
    from fymo.remote.identity import _ensure_uid

    uid, _set_cookie = _ensure_uid(environ)
    with request_scope(uid=uid, environ=environ):
        return project_identity()
