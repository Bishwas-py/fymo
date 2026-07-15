# Journal Entry 019: Two Booleans Pretending to Be One Decision

**Date**: July 15, 2026
**Focus**: Collapsing remote.explicit_optin and remote.allow_implicit into a single remote.mode
**Status**: Shipped

## The Complaint That Started It

Someone asked why we needed two differently-named config keys for what
looked like the same boolean. Fair question, and the honest answer was
worse than "we don't": they weren't the same boolean at all, and they
weren't independent either. `allow_implicit` only ever got read when
`explicit_optin` was already false. One controlled what the router would
actually dispatch. The other only controlled whether the build would
complain about it. Two flags standing in for three real states, and the
fourth combination nobody had ever thought about, both set at once, just
happened to resolve to something sane by accident of read order, not by
design.

## The Bug In My Own Plan

I wrote a truth table before touching any code, the usual thing, map every
input to its output, hand it to whoever implements it. `explicit_optin:
true` mapped to `hygiene_enforced: true` in my first draft, because that
felt symmetrical: opt-in is on, so the check should be on too, right?

It's backwards. Once dispatch is actually gated, the hygiene check has
nothing left to warn about, an undecorated function in strict mode is
already safely unreachable, checking it anyway just false-flags private
helpers that were never a problem. The review caught this before it ever
reached the wiring task, by doing something I hadn't: diffing my resolver's
output against what the *existing* code actually did today, line by line,
instead of trusting my own table. I was reasoning about what felt
consistent instead of what was already true on main. Fixed the table,
fixed the resolver, moved on. Small thing to get wrong, would have been an
annoying thing to discover after it shipped.

## Finding My Own Work Half-Done

Task two was supposed to wire the resolver into the three places that
actually read the old flags. When I came back to it, two of those three
were already done, uncommitted, sitting in the worktree. I don't fully
know how, some earlier pass at this must have gotten interrupted mid-task.
What worried me wasn't that it existed, it was that when I ran the tests
meant to prove the missing third piece was missing, they skipped instead
of failing. Silently. A fixture dependency wasn't installed, so the tests
that would have told me the work was incomplete just didn't run at all,
and an incomplete job would have looked identical to a finished one if I'd
trusted the green checkmark instead of asking why there was a checkmark on
something I hadn't verified. Installed what was missing, watched the real
failures show up, finished the actual work.

## The Rebase Nobody Asked For But Everybody Needed

By the time this branch was ready to merge, five other things had already
landed that touched the same ground I was standing on. One of them, a fix
for a bug where interpolated config strings evaluate truthy no matter what
they say, patched the exact two flags this branch was retiring, at their
old location, because the new location I was building didn't exist on main
yet when that fix was written. Correct call on their part, you can't patch
a file that doesn't exist.

But it meant my own resolver, sitting untouched since before that fix
existed, still had the identical bug inside it. `explicit_optin: "false"`
from an interpolated env var would have evaluated true the moment this
branch merged, silently reintroducing a bug that had just been fixed
somewhere else, in the exact commit that was supposed to be the permanent
home for that logic. Not a merge conflict, git would have let this through
without a single complaint, because two branches editing different files
doesn't look like disagreement to source control. It only looks like
disagreement if you know what both changes were actually for.

Pulled the fix in directly rather than let it regress: the coercion now
lives inside the resolver itself, once, so nothing that calls it has to
remember to ask for it separately. Checked it by hand afterward, not by
reading the diff and assuming it worked, by actually calling the resolver
with the string `"false"` and asserting what came back. It came back
false. Correctly, this time, permanently, not by luck of merge order.

## The Numbers Nobody Will Remember But Everyone Depends On

Five different branches landed journal entries this week and every single
one of them independently reached for the number thirteen, because five
people checked "what's the next number" against a main branch none of them
had seen the others' answer to yet. Not a bug in any one of them, just
what happens when five things move at once and only discover each other at
the exact moment they try to occupy the same slot. Renumbered as each one
landed instead of fighting about which was "really" thirteen. None of them
were wrong, the number just isn't the point, the story underneath it is.

---

*End of Journal Entry 019*
