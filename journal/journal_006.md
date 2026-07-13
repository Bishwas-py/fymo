# Journal Entry 006: Auth Providers - Two Axes, Not One

**Date**: July 12, 2026
**Focus**: Extensible auth (password / OAuth / Clerk) + gating the blog's comments
**Status**: ✅ Shipped

## The Setup

Fymo's auth core was solid but hardcoded to one flow: email/password, with
`signup`/`login`/`logout`/`me` living in core and `current_user()` reading a
single signed `fymo_session` cookie. Storage was already pluggable through
the `UserStore` Protocol, but the authentication *flow* wasn't. Adding
Google OAuth or Clerk would have meant editing framework internals. Not
acceptable for something calling itself extensible.

## The Insight That Unlocked It

Providers differ along two independent axes, and conflating them is exactly
what makes OAuth and hosted auth painful to bolt on later:

- **Axis A, the handshake**: how a caller proves identity. A credential
  check (remote function call), an OAuth redirect dance (top-level HTTP
  routes), or nothing server-side at all (Clerk's widget does it client-side).
- **Axis B, session resolution**: how `current_user()` names the caller. A
  fymo signed-session cookie, or verifying an external JWT on every request.

A design that only models "a login function" can't express Clerk, which has
no server login endpoint at all. Once I saw the two axes, the Protocol
wrote itself:

```python
class AuthProvider(Protocol):
    id: str  # "password", "google", "clerk"

    def remote_functions(self) -> dict[str, Callable]: ...  # Axis A, credential
    def http_routes(self) -> list[HttpRoute]: ...           # Axis A, redirect
    def resolve_session(self, environ) -> Optional[User]: ...  # Axis B
```

A provider implements only the hooks it needs (a base class supplies inert
defaults). The framework never branches on provider type; it just calls the
three hooks. Adding a provider adds zero conditionals to core.

`current_user()` became a resolver chain: the built-in fymo-session
resolver first, then each provider's `resolve_session`. First match wins.
Password and OAuth logins write a fymo session; Clerk never does; the call
site can't tell the difference.

Config picks providers in `fymo.yml`, with bare strings for built-ins and
a dotted `class:` path as the escape hatch for anything custom. This
registry pattern turned out to be so useful it got reused twice more later
(jobs, broadcasts).

## Proving It on the Blog

Same day, wired real auth into the blog example: logging in unlocks
commenting, reads stay anonymous. The satisfying part is how little app
code it took:

- `auth.enabled: true` in fymo.yml (the build then emits a typed
  `$remote/auth` client, no backend written by hand)
- One `@require_auth` decorator on `create_comment`
- A small runes store (`app/lib/auth.svelte.js`) wrapping `$remote/auth`,
  shared by the Nav and the comment box so auth state has one source of
  truth

Deliberately out of scope: comment authorship columns, gating reactions,
password reset, email verification, OAuth in the example. The demo's job
was proving the gate, not building a product.

## Known Wart

SSR has no request scope at render time, so the logged-in Nav state
appears only after hydration. A brief logged-out flash. Acceptable for the
example; fixing it properly (session-aware SSR) landed later as part of
production readiness.

---

*End of Journal Entry 006*
