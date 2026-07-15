# Journal Entry 013: The Provider That Made Every App Reinvent Itself

**Date**: July 15, 2026
**Focus**: ClerkProvider derives its own config instead of making every app write a wrapper for it
**Status**: Shipped

## What a Real App Was Doing

I went looking at a live app built on fymo and found a file called
`app/lib/clerk_env.py`, about seventy lines, whose entire job was: read
`CLERK_ISSUER` or decode it out of `PUBLIC_CLERK_PUBLISHABLE_KEY`, build a
JWKS URL from it, and only construct the real `ClerkProvider` if any of that
actually resolved to something. None of that is specific to that app. It's
just what Clerk is. Every single app that wires up Clerk on fymo would need
to write the same seventy lines, because `ClerkProvider.from_config` took
`issuer` and `jwks_url` as flat required keys with no derivation, and never
overrode `is_configured()` even though the framework already has a
mechanism built for exactly this — `required: auto`, which skips a provider
entirely if it isn't configured instead of crashing or half-registering it.
The mechanism existed. Clerk just never plugged into it.

## What Clerk Actually Publishes

The publishable key Clerk hands out (`pk_test_...` / `pk_live_...`) isn't
an opaque token — the part after the prefix is base64 for the Frontend API
domain with a trailing `$`. Decode `pk_test_Y2xlcmsuZXhhbXBsZS5jb20k` and
you get `clerk.example.com$`. Every Clerk app already has this key sitting
in its frontend env for the client widget, so there's no reason the backend
should need a second, separately-configured issuer URL when it can just
read the same key and derive one. That's the whole crux of the fix: the
issuer resolves from `CLERK_ISSUER` if it's set, and falls back to decoding
the publishable key if it's not, and the JWKS URL derives from whichever
issuer it lands on (`{issuer}/.well-known/jwks.json`, Clerk's own
convention) unless something explicit overrides it.

## The Design Calls the Issue Left Open

A couple of things weren't fully pinned down and I had to just decide:

- **What counts as "configured."** `is_configured()` is called by the
  registry with no arguments — it can't see whatever's actually written in
  `fymo.yml`, only the environment. So it can only ever answer "does the
  environment have enough to build this," not "does this specific config
  entry have enough." An app that hardcodes a literal `issuer:` in its yml
  without setting either env var, and also opts into `required: auto`, will
  see Clerk silently skipped even though `from_config` would have worked
  fine with the literal value. I decided that's fine, because an app in
  that position doesn't need `required: auto` in the first place — it
  already knows Clerk is configured, that's why it hardcoded the value.
  `required: auto` exists for the "maybe configured, maybe not, depends on
  environment" case, and that's exactly what env-only `is_configured()`
  answers correctly.

- **What happens when nothing resolves.** Previously this was a bare
  `KeyError: 'issuer'` if you forgot the config and weren't using
  `required: auto`. I made it a real error message naming both env vars,
  since a stack trace pointing at a dict lookup inside the framework isn't
  something an app author should have to decode.

- **Malformed keys degrade instead of crashing.** A key with the wrong
  prefix, bad padding, or garbage where the domain should be just resolves
  to "not configured" rather than raising out of `is_configured()`. Getting
  that classification wrong (treating a bad key as valid) would be worse
  than getting it right slowly, so the decode function fails closed.

## Doing It the Way the Repo Already Does It

Wrote the failing tests first — explicit issuer without env, `CLERK_ISSUER`
alone, publishable-key derivation alone, one env winning over the other,
explicit values winning over both, the missing-everything error, and
`is_configured()` in each of those states, plus the full path through
`build_providers()` with `required: auto`. Watched all of them fail for the
right reason: the derivation tests died on the same `KeyError` the app's
wrapper existed to work around, and the `is_configured()` tests failed
because `BaseProvider`'s default just always says yes. Then wrote the
actual derivation and the override, and watched the same tests turn green
without touching anything else about the provider — the constructor still
takes plain `issuer=`/`jwks_url=` kwargs exactly like before, so nothing
that constructs `ClerkProvider` directly noticed a thing.

Full suite stayed green throughout, and I ran the zero-config path for
real — set only the publishable key in the environment, called
`build_providers` with `{type: clerk, required: auto}`, and confirmed it
produced a working provider with the right derived issuer and JWKS URL,
then cleared the environment and confirmed the same config just quietly
produced nothing instead of an error. That's the actual behavior an app
depending on this would see, not just an assertion on a return value.

Independent review came back clean — traced the base64 edge cases (wrong
prefix, bad padding, non-ascii, empty domain after stripping the
terminator) and didn't find a gap, confirmed the explicit-wins-over-env
precedence matches how the existing OAuth and OIDC providers already do
config resolution, and confirmed nothing in the diff broke backward
compatibility for apps already passing explicit values. It did point out
two thin spots in the test matrix — explicit issuer against a conflicting
env var, and a key with the right shape but a body that just isn't valid
base64 — so I added both before calling it finished.

## What This Actually Changes

`fymo.yml` goes from a custom wrapper class plus explicit issuer and JWKS
URL, down to:

```yaml
auth:
  providers:
    - type: clerk
      required: auto
```

Dormant until Clerk env vars show up, active the moment they do, no app
code standing between "I have a Clerk account" and "this works." The
seventy-line file that started this doesn't need to exist anywhere anymore.

---

*End of Journal Entry 013*
