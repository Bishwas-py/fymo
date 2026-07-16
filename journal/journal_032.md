# Journal Entry 032: The Conftest Everyone Kept Rewriting

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
session, never the client. Full suite green, and the only skips are the
same Postgres-gated provider tests that skip everywhere without
TEST_DATABASE_URL. (Final counts are in the postscript below; the tally I
first wrote here went stale within a day.)

## Postscript: The uid That Rode Along

Caught before merge, and I'm glad it was: acting_as swapped the user and
nothing else. current_user() flipped to bob, but the uid in the request
scope, set once by signed_in, rode along unchanged, so both identities
were the same anonymous caller the whole time. blog_app's own reactions
table is what made the miss concrete instead of theoretical. Reactions
are keyed purely by uid, so signed_in(alice) plus acting_as(bob) plus
toggle_reaction had bob toggling alice's clap OFF. The cruel part is the
shape of the failure: an isolation test written in good faith over that
API would go green for exactly the wrong reason, and a green isolation
test that lies is worse than no test at all.

The fix was settling a rule rather than patching the symptom: identity
is user plus uid, and the uid follows the user, derived as
u_test{user.id} for both signed_in and acting_as, with an explicit uid=
escape hatch when a test cares about the exact value. acting_as
snapshots the event's uid and restores it in a finally, so nesting and
exception exits unwind level by level, and signed_in stopped handing
every block the same shared constant while I was at it. The regression
tests live where the miss lived: blog_app now asserts alice's and bob's
comment rows carry different uids, and a reactions test insists bob's
clap takes the count to two instead of erasing alice's. Full suite now
stands at 938 tests, 928 passing, same ten Postgres-gated skips.

---

*End of Journal Entry 032*
