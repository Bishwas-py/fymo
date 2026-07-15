# Journal Entry 016: The Decorator That Was Telling the Truth

**Date**: July 15, 2026
**Focus**: Closing the gap between "require_auth works correctly" and "require_auth actually protects anything"
**Status**: Shipped

## A Bug Report About Code That Isn't Wrong

This one started strange. The issue wasn't "require_auth is broken." It was
the opposite: require_auth is correct. No session means 401, every time,
no matter why there's no session. Someone had gone looking for a bug in it
and hadn't found one, because there isn't one.

What they'd found instead, on a real app, was a hand-rolled wrapper around
require_auth. The app's own code, not fymo's. It checked whether the right
env vars were present before deciding whether to enforce auth at all, and
if they weren't, it fell through to a no-op. The intent was reasonable on
its face: let local dev run without wiring up a real auth provider first.
But the check it used to decide "is this local dev" was "are the env vars
set", and a prod box that simply forgot to set one env var looks
identical, from inside that check, to a laptop that never got them in the
first place. Every mutation behind that wrapper went unauthenticated, and
nothing anywhere said so.

I can't fix code that lives in someone else's app. What I can do is make
sure the framework itself would have caught the underlying condition that
made the app-level shortcut tempting in the first place: shipping
@require_auth with no way for anyone to actually get a session.

## The Precedent Question

The issue left a real decision open: should this be an opt-in check, the
way #8's remote-exposure enforcement started, or on by default, the way
#16's storage check is. I went back and reread both.

#8 needed the gradual opt-in because implicit remote exposure was the
existing, deliberate default — every app already relied on it, and turning
it into a hard failure overnight would have broken working code doing
exactly what it was supposed to do. #16 has no such excuse: media
configured with no storage section has never been a valid app shape, so it
just fails the build, no flag, no escape hatch.

@require_auth with zero active providers is the second kind of problem,
not the first. There's no app where that combination is intentional — it's
either dead code that will 401 forever, or it's inviting exactly the kind
of app-side workaround that filed this issue. So I built it unconditional,
same as storage, and said so directly in the code rather than leaving the
decision implicit. The one thing I did carry over from precedent was
gating on `dev`: `fymo build` fails, `fymo dev` doesn't, matching the
existing "zero routes" check, because an app mid-setup locally with auth
not wired up yet is a completely normal state that shouldn't block
iteration.

## Making require_auth Say What It Is

The check needed a reliable way to find every @require_auth site without
re-deriving the answer by calling functions and checking status codes.
fymo already had exactly this pattern for a different decorator — `@remote`
stamps `__fymo_remote__ = True` on the function object it's given, and the
build-time exposure check just looks for that attribute. I did the same
thing to require_auth: its wrapper now carries `__fymo_require_auth__ =
True`, set after `functools.wraps` runs so it survives regardless of
whether `@remote` sits above or below it in the stack. Wrote the stacking-
order tests before the implementation, watched them fail because the
attribute didn't exist yet, then added the one line that made them pass.

From there the check itself is a straight copy of the shape
check_remote_exposure_hygiene already established: walk app/remote/*.py,
import each module, look for the marker, and if anything's marked, decide
whether auth.enabled is actually true and whether the configured providers
resolve to anything. Zero providers or auth off, and the build fails
naming the exact file and function.

## Proving It For Real

Unit tests passing wasn't enough for something framed as closing a
security gap. I scaffolded a throwaway app off todo_app, gave it a
`@require_auth` function with no auth config, and ran the actual `fymo
build` binary against it. It failed with the message I'd written, pointing
at the exact function. Added `auth: {enabled: true}` — nothing else, just
that one line, letting the default password provider kick in — and ran it
again. Clean build. That's the whole point of the check: the fix for the
misconfiguration is one line in fymo.yml, and now the build tells you
that instead of staying quiet.

## What Review Caught

I asked for an independent pass before calling this done, same as every
issue before it, and it earned its keep. My check's own docstring claimed
it would catch a provider "declining via required: auto (e.g. its env var
was never set in prod)" — which is literally the scenario from the issue.
But I'd only tested that against a custom provider class that overrides
`is_configured()`. The reviewer went and checked the built-in providers —
google, oidc, clerk — and none of them override it. `BaseProvider`
defaults `is_configured()` to True, and the OAuth providers read their
client id and secret via `os.environ.get(key, "")`, silently falling back
to an empty string rather than declining. So a real app that reached for
`type: google, required: auto` expecting exactly the protection this issue
asked for would get a provider that "counts" as active while being
completely unable to authenticate anyone.

That's not a bug in what I shipped — required: auto already worked exactly
as documented, and I didn't touch oauth.py or clerk.py. But my check's own
comments were overselling what it actually covers, and that's a real
problem in code whose whole job is to be trusted at face value. Fixed the
wording to say precisely what's true today: it catches providers that
implement is_configured(), which right now means custom provider
subclasses, not the built-in OAuth ones. Giving the built-in providers a
real is_configured() is worth doing, but it's a change to the provider
layer, not to a build-time check, and bundling it in here would have meant
shipping a bigger, less reviewable diff for a problem that deserves its
own attention. Left a clear note about it instead of quietly letting the
gap ride on optimistic docstring language.

## The Count

780 passing, 10 skipped, zero failed with node available for the example-app
fixtures; the same suite clean at 681/109 without it. Six files touched,
under 400 lines, and the real proof wasn't the test count — it was running
the actual CLI against a broken app and watching it refuse to build, then
watching one line of config fix it.

---

*End of Journal Entry 013*
