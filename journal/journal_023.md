# Journal Entry 023: A Place to Put What the User May Do

**Date**: July 16, 2026
**Focus**: Identity extras, the request-scoped slot issue #57 asked for
**Status**: Shipped

## The Missing Slot

fymo answers "who is this" completely. Custom resolvers, the session
cookie, token providers, all of it works. The moment an app asks "what is
this user allowed to do", it needs data sitting next to the identity, an
org id, roles, scopes, and fymo gave that data nowhere to live. I know
because a real app built on fymo re-fetched permission rows inside every
remote function that needed them, then hand-rolled a module-level cache
keyed by user id to make that bearable. Both worse than the framework just
providing the slot.

Going looking for the slot confirmed there wasn't one. User is a frozen
dataclass, nothing can be added. RequestEvent is also frozen, and it gets
rebuilt from the raw event dict on every request_event() call, so there's
no stable object to hang anything on. current_user() re-walks the whole
resolver chain on every single call, no per-request memo to piggyback on.
The one mutable per-request thing in the entire system is the plain dict
the request-scope contextvar holds. That dict is where extras now live.

## The Setter That Would Never Run

My first shape was the obvious one: set_identity_extras(mapping), called
from inside your session resolver, read back with identity_extras(). Write
the API, register a resolver in the test, done by lunch.

Then I traced who actually gets to run during session resolution. The
chain is the built-in fymo-session resolver first, then registered ones,
first non-None wins. Which means for every app using fymo's own sessions,
the majority case and the exact case the permission-cache app was in, the
built-in resolver resolves the user and returns before any app code
executes. A setter "called during session resolution" has nowhere to be
called from. The shape only worked for apps that had already replaced
fymo's auth with their own resolver, the people who needed it least.

So the population point is a hook instead. register_identity_extras_hook
takes a function of the resolved User, and current_user() fires the hooks
once per request scope, right after whichever resolver in the chain
resolved, built-in or provider, then freezes the merged result into the
event dict. fymo never looks inside it. Absent means an empty mapping,
never an error, and outside a request scope the accessor raises the same
RuntimeError request_event() does. The hook running once per scope also
quietly kills the hand-rolled cache: a hook that hits the database runs
one query per request, not one per check.

## The Memo I Didn't Add

While in there it was tempting to memoize the resolved user too, since the
sentinel machinery was right at hand. I left it alone, and my first reason
for leaving it alone turned out to be wrong. I had convinced myself the
SSE broadcast path holds a request scope open for the lifetime of a
connection, where a memoized user would freeze identity for hours.
Re-reading sse.py instead of trusting my memory of it: the scope wraps the
authorization guard call only and closes before the stream ever starts.
The hours-long scope I was defending against does not exist.

The decision still stands, on real ground this time. current_user()
re-walking the chain on every call is observable behavior the resolver
tests exercise directly, resolvers get registered and swapped and the walk
is expected to see the change. A silent memo would rewrite those semantics
as a side effect of an unrelated feature. Extras get frozen per scope on
purpose, that is their contract. Identity resolution keeps its re-walk
because nothing about this issue asked me to change it.

One thing I did verify rather than assume: SSR controllers run inside the
same request scope remote functions get, when auth is enabled, so extras
set by a hook are readable from getContext and layouts too. The honest
footnote is that SSR opens one scope per controller invocation, so "once
per request" there means once per getContext call. The hook's docstring
carries that caveat now.

## The Hook That Registered Itself Three Times

After the first cut I went back over where an app would actually call
register_identity_extras_hook from. The natural place is the top level of
an app module, and in a dev process that module body runs up to three
times: the hygiene check, the guarded-sites scan, and discovery each
reload it through importlib. Every pass appended another copy of the hook,
so the one-query-per-request promise quietly became three queries in dev,
and no value-based assertion could catch it, the merged result was
byte-identical.

The obvious fix, deduplicating by function identity, does not work: every
reload creates a brand new function object. What survives a reload is the
definition site, module, qualname, file, line, so registration now
replaces the stale entry whose site matches instead of appending. Two
different lambdas in one scope still differ by line, which the merge test
proves, and a new test builds a scratch module, reloads it twice, and
asserts exactly one hook fires exactly once per scope. The resolver chain
solved this same problem by resetting before re-registering, but hooks
can't borrow that trick, nothing between the three reload passes ever
re-runs the reset point. With the dedup and a test pinning the returned
mapping as read-only, the suite stands at 920 for 920.

## Ten Skips That Weren't Free

The full suite came back green with ten skips, all Postgres-gated tests
wanting a TEST_DATABASE_URL. Easy to wave off as environmental. Instead I
checked what was actually running on this machine and found the Postgres
container from the issue-50 work still up. First attempt failed on a
guessed password, the container wanted fymo, not postgres, and the job
tests needed the procrastinate extra installed. With both fixed, all ten
formerly-skipped tests passed against the real database, and the suite
finished 917 for 917, zero skips. A skip you haven't explained is just a
failure you haven't met yet.

---

*End of Journal Entry 023*
