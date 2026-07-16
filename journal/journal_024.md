# Journal Entry 024: The Queue You Could Only Read With psql

**Date**: July 16, 2026
**Focus**: `fymo jobs-status` — surfacing job state the providers already track (issue #52)
**Status**: Shipped

## The Complaint Was Fair

Issue #52 came straight from lived pain: on a real project, answering
"is this job stuck" meant opening psql, reading `pg_stat_activity`,
checking whether an app table row had moved, and tailing worker logs,
every single time. The irritating part is that the information was
sitting right there the whole time. Procrastinate keeps a status column
on every job it has ever queued. fymo just never handed anyone a way to
look at it, and the docstring in `fymo/jobs/__init__.py` saying "job
state is not tracked here" read less like a design boundary and more
like an excuse.

So the shape of the fix was clear before I wrote anything: don't build a
tracking system, build a window into the tracking that already exists.

## An Optional Seam, Not a New Obligation

The `JobProvider` seam got two read-only methods, `job_counts()` and
`list_recent_jobs(limit)`, with base defaults that return `None`.
`None` means "this provider doesn't track job state", and it's
deliberately distinct from an empty dict or empty list, which mean
"tracked, and there's nothing there". That distinction is the whole
contract: the CLI can tell "no jobs" apart from "no idea", and existing
custom providers stay valid without writing a line, because the inert
default answers for them honestly.

Procrastinate's implementation is half public API, half not, and I want
to be precise about why. Counts come from `JobManager.list_queues()`,
which procrastinate exposes exactly for this, per-queue aggregates by
status, summed across queues. The recent-jobs list is where the public
API let me down twice: `list_jobs()` has no LIMIT (it fetches the whole
table, which `delete_old_jobs` may never have pruned), and its `Job`
model carries no enqueue timestamp at all. Both things live in
procrastinate's documented schema though, so `list_recent_jobs()` is one
query against `procrastinate_jobs` joined to the `procrastinate_events`
row the insert trigger writes when a job is first deferred. That
'deferred' event is the queued-at time. I don't love bypassing the
public API, but I wrote down exactly why next to the query, so if a
future procrastinate grows a proper paginated listing, the fallback has
its own eviction notice attached.

## The Trap in "Implement What You Can"

The threaded provider almost got a real implementation. The executor
knows how many jobs are queued and running; wiring up counters would
have been an afternoon. Then I walked through who would actually call
this, and the whole idea fell apart: `fymo jobs-status` runs as its own
OS process. The executor whose state matters lives inside the web
process. The provider the CLI builds is a fresh one, three seconds old,
with an empty pool. Any counts it reported would always, structurally,
be zero, and a status command that confidently prints zeros while your
web process churns through a backlog is worse than no command at all.

So threaded returns `None`, on purpose, with the reasoning written into
the class docstring. The CLI turns that into an exit-1 message pointing
at the durable providers and the docs. Sometimes the honest feature is
a well-worded refusal.

## The Bug Only the Real Binary Showed

Tests were green the whole way, and then the first real run against a
throwaway Postgres container printed the status table beautifully and
followed it with a `PythonFinalizationError` traceback from psycopg's
connection pool. The provider's sync connector had never been closed
anywhere, and it never mattered before, because the only process that
opened it was the long-lived web server. A CLI that exits milliseconds
after connecting is a different animal: the pool was getting torn down
by interpreter shutdown, and Python 3.14 objects loudly to joining
threads that late.

The fix grew the seam by one more method, `close()`, inert by default,
and on procrastinate it closes the cached app and drops it so a later
call reconnects transparently. The CLI calls it in a finally block,
guarded with getattr because a custom provider written against last
week's contract won't have it. What sticks with me is that no unit test
would have caught this, the noise only exists at interpreter shutdown
of a short-lived process. Running the actual binary against an actual
database is not a formality.

## Watching It Earn Its Keep

The best moment of the day was accidental. While demoing the command
end to end, I pointed a worker with only a `boom` task at a database
that still held `add_numbers` jobs from the test suite. The worker
failed them all with "Task cannot be imported", and `fymo jobs-status`
showed it instantly: `failed 6`, newest rows on top, each with its
queued-at time. That is, beat for beat, the debugging session the issue
author described doing by hand in psql, except it took one command.

## Where the Boundary Now Sits, In Writing

The issue asked for three things and explicitly said that if any were
scoped out, the docs should say so rather than leave the absence
looking like an oversight. So docs/conventions.md now has the whole
position: the status command for what providers track, the statement
that fymo does not and will not track job progress or results (progress
is app domain data; a fymo-owned progress store would be a second,
worse database next to the one the app already has), and the convention
for apps that want progress anyway: a `job_runs` row keyed by an id the
submitter chose, updated by the task, read back through a remote
function or a broadcast channel. The web-reachable status view stayed
out of scope. It drags in auth and exposure questions that deserve
their own issue instead of riding along on this one.

## The Count

800 passing, up from 784, and 127 skipped without a database. With
`TEST_DATABASE_URL` pointing at the throwaway container the
procrastinate suite runs for real: the counts test watches two jobs go
todo to succeeded through an actual worker, and the close test proves a
closed provider reconnects instead of bricking. The tests I care most
about are the two that pin the `None` contract, because that's the line
between "fymo doesn't know" and "fymo pretends to know", and this whole
issue existed because pretending is what hand-written psql sessions are
made of.

---

*End of Journal Entry 024*
