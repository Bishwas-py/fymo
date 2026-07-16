# Journal Entry 024: The Conftest Everyone Kept Rewriting

**Date**: July 16, 2026
**Focus**: fymo.testing, so apps stop spelunking in fymo's own test suite
**Status**: Shipped

## The Complaint

Issue #48 said it plainly: every app built on fymo with real auth and real
storage ends up re-deriving the same handful of conftest lines, and the
only place to learn the correct pattern is fymo's internal tests, which
were never meant to be documentation. Simulating a signed-in caller,
simulating a second different caller to prove user B can't touch user A's
data, and getting get_storage_provider() to work at all in a process that
never constructs a FymoApp. Three things, none hard, all undiscoverable.

## The Assumption I Walked In With

I started by rereading tests/auth/test_resolvers.py, expecting to package
up everything its fixture does: install a secret, build a SqliteUserStore,
mint a session token, hand it in as a cookie. That was the wrong shape,
and the resolver chain itself is what told me so. current_user() walks the
built-in cookie resolver first, and with no fymo_session cookie present
that resolver returns None before it ever touches the user store. So a
fake session needs no store, no secret, no token at all. Register one
resolver that returns your User, open a request scope, done. The utility
became a thin wrapper around register_session_resolver plus request_scope,
the exact mechanism real providers use, rather than a parallel
implementation that could drift from it.

That collapse made the second utility nearly free. The resolver doesn't
close over a user, it reads one from a contextvar. signed_in() sets it,
acting_as() swaps it and restores it on exit through the contextvar token,
and nesting to any depth falls out of that without any bookkeeping I had
to write. Proving B can't act as A is now two lines in the middle of a
test instead of a second hand-rolled fixture.

## Cleanup Is the Product

The part I went back and forth on was teardown. The tempting version of
signed_in's exit path is reset_session_resolvers(), one call, registry
empty. But a test may have registered its own provider resolver before
entering the block, and nuking the whole chain would eat it. So the block
removes exactly the one resolver it registered and nothing else, and
there's a test pinning that: pre-register a sentinel, run a signed_in
block, assert the registry holds exactly the sentinel afterward.

Same posture for init_providers. It mirrors FymoApp.__init__'s order,
storage only when fymo.yml configures it, jobs and broadcasts always with
the same defaults, but on exit it restores the previous provider
singletons rather than resetting them to None. A test that had already
installed something deserves to get that something back, not a blank
slate. The back-to-back test takes a full snapshot of every registry,
runs two utility blocks in sequence, and asserts the snapshot is
byte-identical after. Journal 021's leak is why that test exists.

One deliberate difference from FymoApp: a missing fymo.yml raises
FileNotFoundError instead of quietly proceeding with an empty config the
way ConfigManager tolerates. A test pointed at the wrong directory should
fail at the with statement, not three asserts later with a confusing
"storage is not initialized".

## Keeping pytest Optional

fymo doesn't depend on pytest at runtime, and the testing module had to
respect that. Everything is a plain context manager, importable anywhere;
the one pytest fixture sits behind a try-import at the bottom of the file
and simply doesn't exist when pytest doesn't. Verified by importing the
module under a blocked pytest import, not by trusting my reading of it.

blog_app got the consumer-side proof: its first tests, and the only
fixture the app itself owns is its database. Alice comments, bob comments
through acting_as, and the assertion is that authorship follows the
session, never the client. Full suite green, 929 tests up from 907, and the
ten skips among them are the same Postgres-gated provider tests that skip
everywhere without TEST_DATABASE_URL.

---

*End of Journal Entry 024*
