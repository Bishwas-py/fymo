# Journal Entry 030: One Expensive Function Shouldn't Share a Budget With Its Cheap Neighbors

**Date**: July 16, 2026
**Focus**: Per-function rate limiting for remote functions (issue #54)
**Status**: Shipped

## The Shape of the Complaint

The middleware rate limiter works, and I still like it: token buckets
keyed by client IP and path prefix, in-process, no Redis, opportunistic
sweep so memory stays bounded. But the key is the problem. Everything
under `/_fymo/remote/` matches one prefix rule, which means the function
that calls an LLM and costs actual money per invocation draws from the
exact same budget as the function that reads three rows out of SQLite.
A retry loop against the expensive one, or a component polling it a
little too eagerly, turns into uncapped real cost, and the only defense
was hand-rolling a second limiter inside your own app code. The issue
asked for something narrow: the same in-process token-bucket approach,
just scoped to a single function. Not distributed limiting. That's still
a v2 problem and I wrote as much in the middleware docstring months ago.

## The Decorator Is the Easy Part

fymo already has a house pattern for "attach metadata to a remote
function without wrapping it": `@remote` stamps `__fymo_remote__`,
`@require_auth` stamps `__fymo_require_auth__` after `functools.wraps`
has done its dict-copying, and there's a test file whose whole job is
proving the markers survive every stacking order. So `@rate_limit`
does the same thing:

```python
@remote
@require_auth
@rate_limit(per_minute=3, scope="user")
def do_the_expensive_thing(...): ...
```

It stamps a frozen `RateLimitRule` on the function and returns the
function untouched. No wrapper means signature reflection and the
router's identity-keyed signature cache never notice it exists. I wrote
the stacking-order tests first, all six permutations that matter, and
watched them fail with a `ModuleNotFoundError` before the module
existed. Cheap insurance, and it caught nothing this time, which is
what it's supposed to do most of the time.

## Not Duplicating the Bucket

The tempting shortcut was a little dict of buckets inside the new
module. I've been burned by that exact move before: entry 012 was
partly about two copies of one rule drifting until the drift became a
dispatch bug. The middleware's limiter already had everything the new
one needs, the bucket math, the lock, and crucially the idle-bucket
sweep that keeps a long-running process from leaking one bucket per
client forever. What it didn't have was a seam: bucket mechanics and
WSGI policy (path rules, environ, config) lived in one class.

So the mechanics moved to `fymo/core/ratelimit.py`: the token bucket,
a `BucketRegistry` owning the lock and the sweep and a single
`check_key(key, capacity, rate)` primitive, plus the trust_proxy-aware
client-IP resolution and the retry-after math. The middleware's
`RateLimiter` now subclasses the registry and keeps only its policy.
Inheritance over composition here for a blunt reason: the middleware
tests poke `rl._buckets` and `rl._last_sweep` directly, and I wanted
those tests passing byte-for-byte unchanged as the proof that behavior
didn't move. They do. The old names (`_TokenBucket`,
`_SWEEP_INTERVAL_SECONDS`) re-export from the middleware module since
that was their original home.

## Scope Is Where the Thinking Was

`per_minute` is easy. `scope` is the part the issue was actually about:
for a cost-sensitive authenticated mutation, the limit that helps is
"per signed-in user," not "per IP" (one NAT'd office shouldn't share a
budget, and one abuser shouldn't get a fresh budget per coffee shop).
Three scopes, each with a decided fallback rather than a silent no-op:

- `ip` resolves the client the same way the middleware does, first
  X-Forwarded-For hop only when `trust_proxy` is on. Same trust
  boundary, same function, literally shared code now.
- `uid` keys on the `fymo_uid` cookie, but only if the HMAC verifies.
  A forged or missing cookie falls back to IP. The subtle trap here:
  the router happily *issues* a fresh uid to a cookieless caller, so
  keying on "the uid this request will end up with" would hand a retry
  loop a brand-new bucket per request. Only an existing verified
  cookie counts.
- `user` keys on the authenticated user's id. Unauthenticated callers
  fall down the uid chain, then IP. The limit always binds on
  something.

One wrinkle: enforcement runs right after the function resolves,
before body parse and argument validation, because an over-budget
caller shouldn't cost more than a dict lookup. But that's also before
the router opens its request scope, and `current_user()` refuses to
run outside one. So the scope-key resolver builds the same event shape
from the raw environ and walks the same resolver chain directly. A
resolver blowing up (say, a stale session cookie on an app that never
enabled auth, where the UserStore seam raises) counts as "not signed
in" and falls through, instead of turning a rate-limit check into a
500.

## The Envelope

Over-limit responses go through the same machinery as every other
domain error: a new `RateLimited(RemoteError)` with status 429, code
`rate_limited`, and a `retry_after` the router now surfaces in the
envelope, transported over HTTP 200 like all envelope errors. App code
can raise it manually too and gets the identical shape. I resisted
adding rate-limit headers to this path; the middleware's 429 already
does headers for the transport-level case, and the envelope is the
contract the `$remote` client actually reads.

## Proving It Outside Pytest

Unit tests can lie about wiring, so I scaffolded a throwaway copy of
the todo example, added a `@remote @rate_limit(per_minute=2)` function,
ran a real `fymo build`, served it with wsgiref, and curled it three
times. First two: `{"type": "result", "result": "[\"charged\"]"}`.
Third: `{"type": "error", "status": 429, "error": "rate_limited",
"retry_after": 30}`. The build's hygiene check also earned its keep by
refusing to build until the function carried `@remote`, which
incidentally exercised the exact decorator stack from the issue sketch
against real code rather than a test fixture.

The suite sits at 810 passing, up from 784, with every pre-existing
middleware limiter test untouched and green.

## What I Left Out

No `fymo.yml` surface. The configuration is per-function and belongs
next to the function it protects; a yml override layer (tighten a limit
at deploy time without touching code) could sit on top of the same
marker later if anyone needs it. And still no cross-worker sharing:
both limiters are per-process by design, and the honest place to fix
that is a shared backend for `BucketRegistry`, which is now one class
instead of two scattered dicts. That was the other quiet payoff of not
duplicating the bucket.

---

*End of Journal Entry 030*
