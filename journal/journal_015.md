# Journal Entry 015: The String That Was Always False

**Date**: July 15, 2026
**Focus**: A typing gap in fymo.yml's ${VAR} interpolation, and three quiet copies of the same bool bug it was hiding
**Status**: Shipped

## The Report

Someone filed it as a small one: `port: ${PORT}` in fymo.yml doesn't
become the int 8000, it becomes the string "8000". True, but not the
interesting part. The interesting part was buried in the second sentence:
"anywhere the config consumer expects a real number or bool, this'll
break or silently misbehave depending what's downstream." I went looking
for where that actually bites, and int() turned out fine everywhere, it
fails loudly on garbage the same as it always has. bool() was the real
problem, and it doesn't fail loudly. It doesn't fail at all.

## Why This One Hides

`bool("false")` is `True`. Every Python developer has tripped on this at
least once and then forgotten about it, because it rarely shows up in
code you'd actually write, nobody does `bool(some_string)` on purpose
expecting string parsing. But that's exactly the shape rate_limit.enabled,
trust_proxy, and security.headers.enabled were in: a dict lookup wrapped
in bool(), written back when the only values that ever reached it were
real YAML booleans or Python literal defaults. The interpolation feature
landed later, in a completely different part of the file, and nothing
connected the two. `rate_limit.enabled: ${RATE_LIMIT_ENABLED}` with
`RATE_LIMIT_ENABLED=false` in the environment silently turns rate limiting
*on* when someone asked for it off. No error, no warning, just the
opposite of the config.

I found the same shape twice more in the middleware settings: security.headers.enabled and trust_proxy. Three call sites in one file, one bug, written by three different moments of "this is obviously a bool, just cast it."

## What I Didn't Do

The obvious escape hatch is a type hint in the placeholder syntax, something
like `${PORT:int}`. I thought about it for a while and put it down. The
whole reason interpolated values are always quoted strings is a real
security fix from a few months back, an env value with a newline and a
fake YAML key in it used to be able to restructure the config file. Adding
a second splice path for "trusted" types means maintaining two code paths
through the exact code that fix closed off, for the benefit of skipping an
explicit cast at a handful of call sites. Not worth it. The framework
already has a working pattern for this: fymo/core/logging.py resolves its
config with explicit string parsing and a fixed vocabulary, fails loud on
anything it doesn't recognize. I wrote a `parse_bool` that does the same
thing, real bool passes through, "true"/"false" strings parse, anything
else raises naming the field.

I also went looking for whether the same thing was true on the int side,
since the bug report's own example was a port number, not a bool. It
wasn't. Every int(...) cast on a config value in this codebase already
fails loudly on a non-numeric string, which is the correct behavior, not
a bug to fix. And the specific example in the report, port: ${PORT}, isn't
actually reachable today: fymo.yml scaffolds a server: block in every new
project, but nothing in ConfigManager has ever read it. I looked hard at
whether to wire that up as part of this fix and decided against it, twice,
for two different reasons. First, nobody asked for it, the bug report was
about typing, not about making dead config live. Second, I checked open
PRs before touching fymo/cli/main.py and found one already in flight
rewriting the exact same serve/dev flag handling I would have touched.
Two people editing the same option definitions with no coordination is
how you get a conflict nobody wanted, over a feature nobody requested.
Left it alone.

## Where The Bug Actually Lived

remote.explicit_optin looked like a one-line fix in server.py, the same
shape as the middleware bugs. It wasn't. Before touching it I went
looking for whether the fix belonged somewhere else entirely, since I
knew there was unmerged work nearby touching this exact flag. There
wasn't, not yet: the file that work was going to introduce doesn't exist
on main. It's real code, reviewed and sitting ready in an open PR, but
until that PR merges the config value still flows through the same old
path it always has. Fixing the file that doesn't exist yet would have
meant fabricating someone else's deliverable and guaranteeing a collision
the moment their PR landed. Fixing the path that's actually live today was
the only fix that was actually a fix.

Then, checking the actual call sites instead of trusting my first grep,
the bug turned out to be in three places, not one. server.py casts it
with a bare bool(...). Two files over, the exact same flag gets read a
second time to decide what goes in the built client manifest, also with a
bare bool(...), independently, never sharing the cast with server.py's
copy. And the build-time hygiene check that's supposed to catch unmarked
functions reads the same flag a third time, plus a sibling flag,
allow_implicit, with no cast at all, just a raw truthy check. Three
readers of the same config key, three separate places for an interpolated
"false" to quietly become "on." Fixing one and leaving the other two would
have meant the manifest, the router, and the build check could each
disagree about whether opt-in was active, which is its own bug independent
of the string-coercion one, so all three got the same fix in the same
pass instead of three separate ones later.

## The One The Review Caught, Not Me

I called it done after that and asked for a final pass over the whole
branch before merging. It came back with a verdict of ready to merge, and
one more thing I'd missed: auth.enabled has the exact same shape, read the
same bare-truthy way in two places, server.py and the same discovery file
as the opt-in flag. Higher stakes than any of the others, too, it gates
whether the whole auth subsystem turns on at all. Nobody had caught it,
not the original bug report, not my own research, not the first pass
through server.py where I was staring directly at the sibling code fifty
lines away.

I'd already cut this branch back once for reaching past what was asked.
Tempting to just fix it and move on since it was small and I was already
in the file, but that's exactly the reasoning that got the scope too wide
the first time, so I didn't. Reported it, named the two lines, said what
it does, and waited. Got a yes. Then it was the same fix as every other
one in this branch, same helper, same shape, done in the time it takes to
write two tests.

## The Count

Zero failed, all previously-green tests still green, plus twenty-two new
ones that exist specifically because they failed first, against the
string "false" and a handful of deliberately garbage values, for the
reason the fix was supposed to close.

---

*End of Journal Entry 013*
