# Journal Entry 021: The Flag the Worker Couldn't Inherit

**Date**: July 15, 2026
**Focus**: fymo jobs-worker --dev, and a test leak worth remembering
**Status**: Shipped

## The Ugly Prefix

Running the worker locally against a project whose secrets live in .env
failed with a missing DATABASE_URL, and the fix was typing
`FYMO_DEV=1 fymo jobs-worker` every time. It worked, which almost made it
worse, an ugly thing that works tends to stay forever.

The web side got cured of this exact disease already: `fymo dev` used to
depend on the caller exporting the flag too, and the fix then was making
the command authoritative about its own mode. The worker never got the
same treatment, and it can't borrow the web process's flag either, it's a
separate OS process, launched separately, inheriting nothing. And .env
can't bootstrap it, since the flag has to be known before .env is loaded
at all. Chicken, meet egg.

So: `fymo jobs-worker --dev`. Sets the flag itself, first thing, before
anything reads it. Default is off on purpose, a forgotten flag on a
production worker must not quietly start reading whatever .env happens to
be lying around in the container. And omitting the flag means no opinion
rather than force-prod, so everyone currently exporting the variable by
hand keeps working unchanged.

## The Leak

The change was four lines. The interesting bug was in my own test for it.

The test deleted FYMO_DEV from the environment up front, using the test
framework's env helper with the don't-complain-if-missing option, then ran
the worker with the new flag, which wrote FYMO_DEV=1 into the real
process environment, exactly as designed. Here's the trap: deleting a
variable that was already absent registers nothing to undo. The helper
restores what it changed, and it had changed nothing. So the 1 my test
wrote outlived the test, and two middleware tests far away in the suite
started failing, rate limiting and HSTS quietly flipped to their dev
behavior by a flag leaked from a test about job workers.

In isolation everything passed, only the full suite caught it, which is
the entire argument for running the full suite even for a four-line
change. Fixed with an explicit snapshot-and-restore fixture and a comment
explaining the trap, because this exact leak pattern has now shown up in
this codebase more than once, and the next person deserves to find the
warning where they'd write the bug.

---

*End of Journal Entry 021*
