"""Per-function rate limiting for remote functions.

The middleware limiter (fymo.core.middleware.RateLimiter) is keyed by
(IP, path-prefix rule), so every function behind /_fymo/remote/ shares one
budget. That's the wrong granularity when one function is expensive or
costs real money per call (an LLM call, a paid third-party API) while its
module neighbors are cheap reads. @rate_limit gives that one function its
own budget, enforced by the router at dispatch time (after the function
is resolved, before its arguments are even parsed).

Same marker-attribute pattern as @remote's __fymo_remote__ and
@require_auth's __fymo_require_auth__: the decorator stamps configuration
on the function object and returns it unchanged, so the marker survives
functools.wraps stacking in any decorator order.

Buckets are per (function, scope-key), in-process, sharing the middleware
limiter's token-bucket core and idle-bucket sweep (fymo.core.ratelimit) so
memory stays bounded. Both limiters stack: the middleware's path-prefix
budget still applies at the WSGI edge.

No fymo.yml surface: configuration is per-function and lives next to the
code it protects.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Callable, Optional, TypeVar

from fymo.core.ratelimit import BucketRegistry, resolve_client_ip, retry_after_seconds
from fymo.remote.errors import RateLimited
from fymo.remote.identity import _UID_COOKIE, _read_cookie, _verify

F = TypeVar("F", bound=Callable)

_VALID_SCOPES = ("ip", "user", "uid")


@dataclass(frozen=True)
class RateLimitRule:
    per_minute: int
    scope: str


def rate_limit(per_minute: int, scope: str = "ip") -> Callable[[F], F]:
    """Give this remote function its own token-bucket budget.

    `per_minute` is the bucket capacity (and refill rate, in tokens per
    minute). `scope` picks what a "caller" is:

    - "ip":   the client IP, resolved with the same trust_proxy awareness
              as the middleware limiter (first X-Forwarded-For hop only
              when `limits.rate_limit.trust_proxy` is on).
    - "user": the resolved identity's uid, from the @identify resolver
              chain (fymo.auth.identity) first, then the legacy session
              resolver chain while the two coexist. When neither identifies
              the caller, falls back to the verified fymo_uid cookie
              identity if present, else the client IP, so the limit always
              binds rather than silently not applying.
    - "uid":  the verified fymo_uid anonymous identity, falling back to
              the client IP when the cookie is missing or fails HMAC
              verification (a cookieless caller must not get a fresh
              bucket per request).

    Two cost/threat trade-offs to know when picking a scope:

    - scope="user" resolves the identity BEFORE the limit binds, so every
      request carrying auth credentials pays the resolver walk (for a
      token provider like Clerk, a JWT verification) even when the answer
      is 429. A clean walk is cached and shared with the handler's
      current_uid() through the request event, so the chain still runs at
      most once per request; the middleware's IP-keyed edge limiter is
      what bounds the walk itself. The per-user budget protects the
      function body and whatever it spends, not the identity resolution.
    - scope="uid" (and unauthenticated scope="user") keys on a cookie the
      server hands out freely, so a determined client can farm several
      valid cookies and rotate them for extra budget. It defends against
      accidental retry loops and over-eager polling, not adversaries; for
      adversarial traffic, "ip" (or the edge limiter) is the backstop.

    Stamps `__fymo_rate_limit__` and returns the function unchanged, so it
    composes with @remote and @require_auth in any order.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"rate_limit scope must be one of {_VALID_SCOPES}, got {scope!r}")
    if not isinstance(per_minute, int) or per_minute < 1:
        raise ValueError(f"rate_limit per_minute must be a positive int, got {per_minute!r}")

    rule = RateLimitRule(per_minute=per_minute, scope=scope)

    def decorate(fn: F) -> F:
        fn.__fymo_rate_limit__ = rule
        return fn

    return decorate


# One registry for the whole process, keyed by ((module, fn_name), scope_key).
# Same seam pattern as identity._secret / auth_context._user_store: the
# remote-function world has no FymoApp reference, so process-wide state lives
# at module level.
_registry = BucketRegistry()


def reset_rate_limit_state() -> None:
    """Drop every bucket (tests / re-init)."""
    global _registry
    _registry = BucketRegistry()


def _cookies_from_environ(environ: dict) -> dict:
    cookies: dict = {}
    if environ.get("HTTP_COOKIE"):
        c = SimpleCookie()
        c.load(environ["HTTP_COOKIE"])
        cookies = {k: v.value for k, v in c.items()}
    return cookies


def _identified_uid(environ: dict) -> Optional[str]:
    """Resolve the @identify chain (fymo.auth.identity), or None.

    Enforcement runs before the router opens the request scope, so the walk
    happens against a ResolverEvent built straight from the environ,
    mirroring request_scope's event shape. A clean walk's outcome (including
    the anonymous None) is cached on the environ under
    ENVIRON_RESOLUTION_KEY; request_scope seeds the request event's
    resolution cache from it, so the chain still runs at most once per
    request even when the handler calls current_uid().

    A resolver raising here counts as "did not identify" and the walk moves
    on to the next resolver (fail-open), the same posture as the legacy
    session walk below: rate limiting runs before the handler, so
    propagating would turn one broken resolver into an outage for every
    call to this function, while falling through only degrades the key to
    the uid/ip tier (the edge limiter still bounds adversarial traffic).
    An unclean walk is NOT cached, so current_uid() inside the handler
    re-runs the chain and propagates per its own fail-loud contract.
    """
    from fymo.auth.identity import (
        ENVIRON_RESOLUTION_KEY,
        Identity,
        ResolverEvent,
        registered_identity_resolvers,
    )
    if ENVIRON_RESOLUTION_KEY in environ:
        return environ[ENVIRON_RESOLUTION_KEY]
    from fymo.core.middleware import resolve_scheme
    from fymo.remote import context as _context
    event = ResolverEvent(
        remote_addr=environ.get("REMOTE_ADDR", ""),
        cookies=_cookies_from_environ(environ),
        headers={
            k[5:].replace("_", "-").lower(): v
            for k, v in environ.items() if k.startswith("HTTP_")
        },
        scheme=resolve_scheme(environ, _context._trust_proxy),
    )
    uid: Optional[str] = None
    clean = True
    for resolve in registered_identity_resolvers():
        try:
            ident = resolve(event)
        except Exception:
            clean = False
            continue
        if ident is None:
            continue
        if not isinstance(ident, Identity):
            clean = False
            continue
        uid = ident.uid
        break
    if clean:
        environ[ENVIRON_RESOLUTION_KEY] = uid
    return uid


def _authenticated_user_id(environ: dict) -> Optional[int]:
    """Resolve the signed-in user's id via the LEGACY session chain, or None.

    Coexistence only: this block walks the same resolver chain
    current_user() does and gets deleted with the User/UserStore model
    (issue #80); _identified_uid above is the successor. The walk runs
    against an event built straight from the environ, since enforcement
    runs before the router opens the request scope. A resolver blowing up
    (e.g. a stale fymo_session cookie on an app with auth disabled, where
    the UserStore seam raises) counts as "not signed in" for limiting
    purposes rather than failing the request.
    """
    try:
        from fymo.auth.context import _fymo_session_resolver, _session_resolvers
    except ImportError:
        return None
    # Mirror request_scope's event shape (fymo/remote/context.py), same
    # trust_proxy-aware scheme resolution included: a resolver reading a
    # key that's absent here would KeyError, get swallowed by the except
    # below, and silently degrade the scope to uid/ip instead of surfacing
    # the mismatch. "uid" is the one deliberate omission, it isn't resolved
    # until the router opens the real scope, and no session resolver reads
    # it (a session is what identifies the caller here, not the anon uid).
    from fymo.core.middleware import resolve_scheme
    from fymo.remote import context as _context
    event = {
        "cookies": _cookies_from_environ(environ),
        "headers": {
            k[5:].replace("_", "-").lower(): v
            for k, v in environ.items() if k.startswith("HTTP_")
        },
        "remote_addr": environ.get("REMOTE_ADDR", ""),
        "scheme": resolve_scheme(environ, _context._trust_proxy),
    }
    for resolve in (_fymo_session_resolver, *_session_resolvers):
        try:
            user = resolve(event)
        except Exception:
            continue
        if user is not None:
            return user.id
    return None


def _verified_uid(environ: dict) -> Optional[str]:
    """The fymo_uid cookie's uid, only if it HMAC-verifies. Never mints a
    fresh uid: a cookieless retry loop would then get a new bucket per
    request and the limit would never bind."""
    raw = _read_cookie(environ, _UID_COOKIE)
    if raw is None:
        return None
    return _verify(raw)


def _scope_key(rule: RateLimitRule, environ: dict) -> str:
    """Map (rule.scope, request) to a bucket-key string.

    Keys are prefixed by kind ("user:", "uid:", "ip:") so a fallback key can
    never collide with a different scope's bucket for the same string.
    """
    if rule.scope == "user":
        uid = _identified_uid(environ)
        if uid is not None:
            return f"user:{uid}"
        user_id = _authenticated_user_id(environ)
        if user_id is not None:
            return f"user:{user_id}"
    if rule.scope in ("user", "uid"):
        uid = _verified_uid(environ)
        if uid is not None:
            return f"uid:{uid}"
    from fymo.remote import context as _context
    return "ip:" + resolve_client_ip(environ, _context._trust_proxy)


def enforce_rate_limit(fn: Callable, fn_key: "tuple[str, str]", environ: dict) -> Optional[RateLimited]:
    """Take a token for this call; return a RateLimited to serialize when
    the function's budget is exhausted, None when the call may proceed (or
    the function carries no @rate_limit marker)."""
    rule: Optional[RateLimitRule] = getattr(fn, "__fymo_rate_limit__", None)
    if rule is None:
        return None
    key = (fn_key, _scope_key(rule, environ))
    allowed, _remaining = _registry.check_key(key, rule.per_minute, rule.per_minute / 60.0)
    if allowed:
        return None
    return RateLimited(retry_after=retry_after_seconds(rule.per_minute))
