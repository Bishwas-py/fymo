# Journal Entry 024: One Connection, Every Thread, Two Posts Wearing Each Other's Clothes

**Date**: July 16, 2026
**Focus**: blog_app's db.py handing every thread the same sqlite3 connection, and the reference example intermittently 500ing under the very server fymo now recommends
**Status**: Shipped

## The Report That Came With Numbers

Someone had already done the expensive part before I ever opened the
issue. Load-tested blog_app under granian, GET / and the remote
get_posts function, 2000 and 4000 requests, with a full table of failure
rates: 0.1% on the SSR route, up to 10% on the remote function route
(the one that does a full DB round-trip with no SSR overhead diluting the
timing window), zero on gunicorn no matter the worker count, zero on a
DB-free route entirely. That table alone told me almost everything about
where the bug lived before I'd read a line of the actual code. gunicorn's
sync workers handle one request at a time, so a race that only needs two
threads never gets the chance to fire. A DB-free route never touches the
one shared thing. And the route doing nothing but hammering the database
failed an order of magnitude more than the one wrapping it in a page
render. That's not "sometimes things break under load." That's a specific
object, shared, getting hit from two directions at once.

The part that made this more than a normal example bug: it's the reference
app. People copy blog_app's db.py into real projects. The issue mentioned
one that already had.

## Reading db.py Like It Was Someone Else's Mistake

`get_db()` is a module-level singleton. First call constructs a `DB`
wrapping one `sqlite3.Connection`, opened with `check_same_thread=False`
specifically so multiple threads *could* call into it without Python's
own safety check stopping them. Every subsequent call, from any thread,
gets back the exact same connection object. `fetchone`, `fetchall`, and
`execute` all go through `self.connect()`, which is that same shared
connection every time.

`check_same_thread=False` doesn't make sharing a connection across
threads safe. It just turns off the one guard rail that would have told
you it wasn't, loudly, the first time you tried. What actually happens
when two threads call `.execute()` and `.fetchall()` on the same
connection at close to the same moment is worse than a clean crash: the
underlying C extension releases the GIL during the blocking parts of a
query, two threads' cursor state gets interleaved, and you get back a
tuple that's short a column, or a row where the title belongs to a
different post than the slug. Not corruption you'd notice from a stack
trace. Corruption that looks like a perfectly fine response with the
wrong content in it.

I checked every call site before deciding anything: the remote functions
in app/remote/posts.py, the subscribe guard in app/broadcasts/posts.py,
the test seed helper. Nothing anywhere assumes two `get_db()` calls share
an open, uncommitted transaction. `execute()` calls `commit()` immediately
after every write. `create_comment` inserts a comment then reads it back
in a second call, `toggle_reaction` writes a reaction then calls
`get_reactions()` fresh, but both of those are sequential calls on one
request's one thread, each already fully committed before the next one
starts. That mattered, because it meant whatever fix I picked didn't have
to preserve any cross-call transactional state. It only had to stop two
different threads from touching the same connection object at the same
time.

## Picking Between Two Honest Options

The issue named the two real choices itself: per-thread connections via
threading.local, or a new connection per request. I went with
threading.local, and the reason came straight out of the call-site read.
A connection-per-request approach would mean opening a fresh sqlite file
handle, running the schema idempotency check, and tearing it back down
on every single `get_db()` call, of which there can be several per
request (toggle_reaction alone makes three). That's real overhead for no
correctness gain, since nothing needs a fresh connection per call. It's
also awkward to wire cleanly into a WSGI app without either a per-request
teardown hook fymo doesn't currently have for the example, or leaking
connections that never get closed. threading.local gets the actual
property that matters, one connection object never touched by two OS
threads, for the cost of a dict lookup, and it's the kind of fix someone
could read once and immediately understand why it's there.

## Red First

Wrote the test before touching db.py. Forty threads, a hundred iterations
each, all released at once off a `threading.Barrier` so they'd actually
collide instead of trickling in one at a time, each one running the exact
same `SELECT ... FROM posts` and checking every returned row's title and
tags actually belonged to its own slug. Seeded eight distinct posts first
so a spliced row would have somewhere obvious to come from.

Ran it against the untouched code. 1820 failures out of 4000 calls. Not a
timeout, not a flake: real `IndexError('tuple index out of range')`
exceptions, and rows like `post-6` showing up with `Title 7`'s
summary and `tag-7`'s tag, exactly the "fields from two different posts"
shape the issue described, reproduced from a plain in-process thread pool
with no HTTP or granian involved at all. That was the moment I trusted the
test was actually testing something real, rather than a comment that
claims thread safety and calls it done.

## The Fix Was Small

Swapped the single `self._conn` for a `threading.local()`, lazily
creating a real connection the first time a given thread calls
`connect()`. Dropped `check_same_thread=False` too, since it's no longer
needed and actively worse to keep: with per-thread connections, the
default `check_same_thread=True` becomes a genuine safety net instead of
an obstacle, it would raise immediately if some future change ever
managed to hand a connection across threads by accident, instead of
silently corrupting data the way the old flag let it.

Ran the new test again. Clean, five times in a row. Ran the full suite:
898 passing, 10 skipped, all Postgres-only.

## Watching It Actually Work, Not Just the Unit Test

A passing concurrency test in isolation wasn't enough to call this done,
not for a bug that was first found under real granian load. Built
blog_app for real, booted it under `fymo serve --prod --server granian`,
and pointed the same shape of load test at it, forty threads times fifty
each, GET / and the remote get_posts call, matching the 2000-per-route
scale from the original report.

First run: 1940 failures on the SSR route, 2000 on the remote route. Not
the bug. Every single one was `HTTPError 429`, fymo's own rate limiter
doing exactly its job against forty threads hammering one address. Had to
laugh at myself for a second before disabling `limits.rate_limit` in the
example's config for the duration of the test, an unrelated bit of the
same app quietly getting in the way of testing a different bit of it.

With the limiter out of the way: 0 failures out of 2000 on both routes,
on the fixed code. To be sure that wasn't just a database file with too
few posts in it to trip anything, I stashed the db.py fix, restarted the
same server on the same build, and ran the same load test against the
original shared-connection code. 12 out of 2000 failures on the remote
route, every one the same `{"type": "error", "status": 500, "error":
"internal"}` body the issue reporter had already seen. Popped the stash
back, rebuilt nothing (db.py needs no rebuild, it's server-side Python,
not part of the client bundle), restarted, ran it again: 0 out of 2000,
twice.

## What a Second Read Turned Up

Had the diff reviewed independently before calling it finished. Nothing
came back Critical or Important, but two things were worth writing down
rather than quietly filing away. First, fymo's own auth store
(SqliteUserStore) already solves this same shared-connection problem a
different way, one connection plus an explicit lock around every access,
rather than one connection per thread. Both are valid. I didn't go change
that file to match, since it's outside this issue and it isn't broken,
but it's the kind of quiet inconsistency worth someone's attention the
next time either file gets touched. Second, granian's prod path and
fymo's own job runner both reuse a fixed pool of worker threads rather
than spinning up a new one per request. Under threading.local, that means
each pool thread keeps its one sqlite connection open indefinitely across
many unrelated requests or jobs, not a bug given everything commits
immediately, but a real shape worth remembering if this pattern ever gets
copied somewhere state does need to reset between calls on the same
thread.

Left the example's blog.db and fymo.yml exactly as they'd been (the rate
limit override and the load-test seed data were never meant to be
committed, both reverted before finishing), and the diff itself stayed
to exactly what the bug needed: one import, one field, four lines inside
`connect()`.

---

*End of Journal Entry 024*
