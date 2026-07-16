# Journal Entry 025: Proving the Second Data Point

**Date**: July 16, 2026
**Focus**: PostgresUserStore, and what "pluggable" actually costs to claim
**Status**: Shipped

## One Implementation Is Not an Interface

The auth store has been a Protocol since day one, with a docstring
promising you can swap it via one line of fymo.yml. Technically true. In
practice, fymo shipped exactly one implementation, SQLite, so "swappable"
meant writing twelve methods from scratch with no second example to copy
from. Meanwhile most real fymo apps already run Postgres, jobs and
broadcasts assume it outright, so the common deployment ended up with app
data in Postgres and user identity in a lonely SQLite file nothing else
knows exists. Two datastores, no foreign key between them, ownership rows
keyed by email string because there's no shared id to point at.

The fix was issue 50's option one: ship PostgresUserStore next to
SqliteUserStore, same Protocol, same constructor shape, so the swap really
is one config line. The store reads DATABASE_URL, the same variable the
job queue and broadcast provider already use, which is the whole point.
Identity lands in the database the rest of the app lives in.

## The Battery Came First

The real deliverable isn't the Postgres class, it's the conformance suite.
Before writing a line of the new store, I pulled every behavior the SQLite
store promises into one battery and parametrized it over store factories:
duplicate email collision, case-insensitive lookup, epoch bumping on
password change, consume-once tokens, superseded tokens, identity linking
where the first link wins. Thirty-three tests, run identically against
both backends. SQLite went green immediately, which proved the battery
described reality rather than my hopes. Then the Postgres half failed with
a missing module, which is exactly the failure you want to see before the
module exists.

Writing the battery also forced honesty about semantics I'd have otherwise
glossed over. A failed INSERT in Postgres aborts the whole transaction,
so there's a test that creates a duplicate, catches the error, and then
keeps using the store, because a backend that forgets to roll back passes
every test except the one that runs after a failure.

## Dialect, Not Redesign

The translation itself stayed deliberately boring. SQLite's UNIQUE COLLATE
NOCASE became a unique index on lower(email). The single locked connection
became a small psycopg_pool, four connections, no tuning knobs, each
method borrowing one for exactly one transaction. Schema bootstrap happens
on first connect like the SQLite store, wrapped in an advisory lock so
eight workers booting at once don't race the CREATEs. Every object is
prefixed fymo_ and listed at the top of the module, because these tables
share a database with app tables and nobody should have to guess which
rows are the framework's.

Two failure modes got promoted to boot time on purpose. Missing
DATABASE_URL raises in the constructor, naming the variable. Missing
psycopg raises naming the exact install command, fymo[postgres]. A store
that waits until the first login attempt to discover it can't connect is
a store that fails in production at 2 a.m. instead of in the terminal at
deploy.

## Run It for Real

Conformance against a mock proves nothing about a database, so the whole
battery ran against an actual Postgres 16, thirty-three for thirty-three,
plus a migration test that builds the table the old way and watches the
store add the missing columns on connect. Then the loader path end to end:
resolve the dotted config path, instantiate with a project root, create
and fetch a user through a real pool. The full suite closed it out, 977
tests, everything green, including the eight-threads-against-a-four-
connection-pool case that makes the pool actually wait.

The Protocol finally has its second data point. Turns out the way to prove
an interface is pluggable is to plug something into it.

---

*End of Journal Entry 025*
