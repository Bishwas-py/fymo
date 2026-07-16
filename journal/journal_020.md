# Journal Entry 020: The Server Was Eating the Framework's Lunch

**Date**: July 15, 2026
**Focus**: Why fymo benchmarked at half of SvelteKit, and what it actually cost to fix
**Status**: Shipped

## The Question That Started It

After the last benchmark round, the obvious question: can fymo get anywhere
near SvelteKit's SSR throughput, or is the gap just what a Python framework
costs? I had two theories going in, one about the WSGI server layer, one
about caching rendered HTML. Rather than argue about which was right, I
profiled.

## The Ladder

The trick was measuring layers in isolation instead of the whole stack at
once. First rung: a bare, do-nothing WSGI app, thirty bytes of hello world,
on the same gunicorn sync worker setup fymo ships with. It managed 2,961
requests a second. An empty app. fymo's full SSR pipeline, real Svelte
rendering through the Node sidecar and all, was doing 2,259 on the same
server, 76 percent of what doing literally nothing gets you.

That one number ended the investigation before it started. fymo was never
slow. Per-request time inside the framework is 0.3 to 0.5 milliseconds,
sub-millisecond for a full server-rendered page. The server in front of it
was throwing that away.

Same bare app on granian, a Rust HTTP server with a Python WSGI interface:
27,022 requests a second. Nine times the ceiling. Then the real test, fymo
unchanged, same built app, same benchmark command, just granian instead of
gunicorn: about 4,300 a second, stable across interleaved runs. From 48
percent of SvelteKit to 79 percent, and the diff was zero lines of
framework code.

## What Fell Out for Free

granian dispatches requests across real concurrent Python threads, which
gunicorn's sync workers never do, a sync worker handles one request at a
time and thread-safety bugs simply never fire. So this was accidentally the
first time fymo core had ever been load-tested under genuine intra-process
concurrency. Six thousand plus requests, zero corrupted sidecar frames,
zero races in the framework. The sidecar's pipe protocol had a lock on it
from day one, and it turns out that lock had never once been contended in
production until this week.

One thing did break: two requests out of two thousand hit an index error
inside the example blog app's own database helper, a single SQLite
connection shared across threads. Not framework code, but it's the
reference app people copy patterns from, so it gets its own fix rather
than a shrug.

## The Part That Needed Actual Care

Making granian a supported server was mostly not about granian. It was
about the sidecar. The gunicorn launcher has a whole carefully-documented
dance: the master process builds the app (and its Node sidecar) before
forking, forked workers would inherit the same pipe file descriptor and
corrupt each other's frames, so the master's sidecar gets stopped and every
worker rebuilds its own right after fork. That dance exists because fork
shares things.

granian doesn't fork the app into workers, each worker process imports the
server module itself, fresh, and builds its own everything. No dance
needed. But "no dance needed" is exactly the kind of claim that has to be
verified against the actual installed source rather than assumed, because
if it were wrong, the failure mode is corrupted render frames under load in
production. Read granian's worker spawn path directly: the target loader
runs inside each worker. Confirmed, and the launcher's docstring now
explains the contrast so the next person doesn't have to rediscover why one
server needs the dance and the other doesn't.

The other property worth defending in code: when you ask for granian
explicitly and it isn't installed, you get a hard error naming the pip
install command, never a silent fallback to gunicorn. Auto mode picks
granian when it's there and gunicorn when it isn't, and says which it chose
and why, out loud, at boot. A server choice that changes your throughput by
2 to 3x should never be invisible.

## Honest Numbers

Re-measured everything through the real CLI at the end, and had it
independently re-measured after that. Per worker, granian carried 2.3 to
2.45x gunicorn's throughput on the same app. At four workers both start
saturating the per-worker sidecar and the gap compresses to about 1.2x.
One number ran the other way: on the static-asset route, no sidecar
involved, gunicorn was actually faster. It's in the docs as measured,
because a recommendation that hides its losing case isn't a
recommendation, it's marketing.

Caching rendered HTML, the other theory, stays on the shelf, written down
with its design constraints for whenever someone wants to go past
SvelteKit instead of near it. The server swap was supposed to be the boring
lever. It was worth three x.

---

*End of Journal Entry 020*
