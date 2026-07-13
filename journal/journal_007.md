# Journal Entry 007: Two Small Primitives - Raw HTTP Routes + a Job Runner

**Date**: July 12, 2026
**Focus**: `app/routes.py` seam for raw WSGI routes, `fymo.jobs.JobRunner` for background work
**Status**: ✅ Shipped (and the job runner got superseded fast, see entry 009)

## Why

Building a real app on fymo (a synthetic browser-monitoring tool) surfaced
two holes the framework had no answer for:

1. Serving a recorded video file with byte-range support. That's a raw
   binary HTTP response with `Range` headers, not an SSR page and not a
   remote function.
2. Running a 30-90 second AI agent session without blocking the request
   that started it.

Both deserved small, generic primitives rather than app hacks.

## HttpRoute

The auth-provider seam already had an `HttpRoute` dataclass for OAuth
redirect routes. I promoted it to a neutral home (`fymo/core/http.py`) and
added `discover_app_http_routes()`: if the app has an `app/routes.py` with
an `http_routes()` function, those routes get mounted in the dispatcher
after fymo's reserved prefixes and before the SSR fallback.

```python
# app/routes.py
def http_routes() -> list[HttpRoute]:
    return [HttpRoute("GET", "/media/videos/", serve_video)]
```

One design choice worth documenting loudly: matching is **prefix match**,
exactly like the existing `/dist/` and `/assets/` dispatch. Not exact
match, not `<param>` templates. The handler parses the rest of the path
itself. Simple, predictable, and consistent with how the rest of the
dispatcher already worked.

## JobRunner

For background work I added `fymo.jobs.JobRunner`: a bounded
`ThreadPoolExecutor` wrapper with a process-wide shared instance
(`get_shared_runner()`). Exceptions get logged and swallowed so one bad job
can't take down the pool or the calling request. The contract: the job
persists its own outcome (a database row), a poller reads that state.
Nothing fancier.

I kept it a pure library on purpose. Zero imports from `fymo.core`, no
automatic FymoApp wiring, apps start it from their own entry point. At the
time that felt right ("apps wire their own background services"). Stdlib
only, both primitives.

## The Honest Postscript

The JobRunner turned out to be a half-measure. It unblocks the *request*,
but the job still dies with the web process, and there's no separate
scaling knob for workers. Building the monitoring app against it exposed
that within days: the dev server was single-threaded, so a long recording
froze every other request anyway, and a deploy would kill in-flight
recordings.

That pain produced the real answer (durable job providers, entry 009). The
JobRunner survives as the zero-config default backend for it. Sometimes you
have to ship the small thing to find out precisely why it's not enough.

---

*End of Journal Entry 007*
