# Journal Entry 023: The Extra That Was Already Half-Built

**Date**: July 16, 2026
**Focus**: Locking auth packaging before more providers land — password stays in base, Clerk/OIDC/OAuth move behind named extras, `type: clerk` fails at boot instead of at first login
**Status**: Shipped

## The Debate I Wanted to Avoid Having Three More Times

Two providers exist today (Clerk, and the Google/OIDC family), a third
kind is clearly coming, and every one of them was going to ask the same
question: does this ship in base fymo, or does it live behind an extra?
Rather than relitigate that per provider, the plan was to answer it once,
write it down, and make the answer actually true in code — not just true
in a paragraph somewhere. Password stays in base because it's really
`hashlib.scrypt`, zero external deps, the one real login a newcomer gets
for free. Clerk needs `pyjwt[crypto]` for RS256-over-JWKS verification.
OIDC and OAuth are pure `urllib`, no deps at all. None of that was in
dispute — it's what "in dispute" turned out to mean underneath that was
the actual work.

## Half-Built Was Generous

Opening `clerk.py` expecting to wire a dependency check from scratch, I
found the lazy import already sitting there:

```python
def verify(token: str) -> Optional[dict]:
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as e:
        raise RuntimeError(
            "Clerk token verification needs the 'pyjwt[crypto]' package; "
            "install it or pass a custom verify= to ClerkProvider"
        ) from e
```

Right idea, wrong moment. That closure only runs when a request actually
carries a token and something calls `resolve_session()` — meaning a
misconfigured production deploy would boot clean, serve pages, look
completely healthy, and only discover the missing dependency the first
time a real user tried to log in. For an auth system, that's close to the
worst possible timing: the failure mode is invisible until someone hits it
live.

The fix wasn't a new mechanism, it was moving one check earlier. The
`__init__` already decides, once, whether to hand `resolve_session` a
custom `verify=` or build the default JWKS verifier:

```python
self._verify = verify or _jwks_verifier(jwks_url, issuer, audience)
```

That `or` is exactly the moment fymo commits to needing pyjwt. Everything
after it — the whole request path — was too late to be the place that
finds out.

## Two Modules, Not One

Writing the availability check, I almost wrote `find_spec("jwt") is not
None` and stopped there. Reading PyJWT's own source first turned up why
that's incomplete: `jwt/algorithms.py` wraps its `cryptography` import in
its own try/except and just flips a `has_crypto` flag to `False` when it's
missing. Plain `import jwt` succeeds with zero crypto backend installed —
it only breaks once you actually ask for RS256, which is exactly what
Clerk's JWKS verification does. `pyjwt[crypto]` is really two packages
under one extra name. The check has to be both:

```python
def _pyjwt_available() -> bool:
    return find_spec("jwt") is not None and find_spec("cryptography") is not None
```

`find_spec` over an actual `import` on purpose — checking availability
shouldn't have the side effect of loading either module, and it gave the
tests a single function to monkeypatch instead of needing to fake entries
in `sys.modules` and hope nothing else in the same process cached a real
import first.

## Borrowing Someone Else's Already-Solved Problem

This exact shape of problem — an optional production dependency, a hard
error when someone explicitly asks for something that needs it, a message
naming the fix — had already been solved once in this codebase, for
granian (`fymo serve --prod --server granian`, issue #39). Same pattern:
a small `_available()` helper using `find_spec`, monkeypatched directly in
tests rather than physically uninstalling anything from the shared dev
venv. I copied that shape instead of inventing my own, down to the
`monkeypatch.setattr(mod, "_x_available", lambda: False)` idiom in the
tests. Consistency wasn't the only reason — it also meant not having to
convince myself a new isolation strategy was actually safe across the rest
of the suite. Borrowed confidence, not just borrowed code.

## The Migration Question I Decided Not to Build a Feature For

The issue asked for something specific: today, `type: clerk` works from a
bare `pip install fymo` as long as pyjwt happens to already be installed,
no extra required. Formalizing the extra shouldn't silently strand anyone
already running that way — the ask was one release with a deprecation
warning for that in-between case, then a hard failure later.

I sat with this longer than the rest of the change combined, because the
honest answer is that "in-between case" isn't a state I can detect. At
runtime, "pyjwt is installed because `fymo[clerk]` was requested" and
"pyjwt is installed because it happened to be lying around" look
identical — same `find_spec` result, same import, same everything. Neither
pip nor uv record, anywhere `importlib.metadata` exposes, which extra of
which package caused a given install. I went looking for a workaround —
inspecting installed distribution metadata, checking `RECORD` files,
anything — and came up empty in any way that wouldn't be fragile and
tool-dependent (pip vs uv record installs differently enough that I didn't
trust it to hold up).

So I didn't build the warning. Writing one that fires whenever pyjwt is
present-but-technically-undeclared would misfire forever on everyone who
did the extra installation correctly — a permanent nag aimed at users who
did nothing wrong, in service of a transition window that's supposed to
end. What I built instead: the one thing that's actually true regardless
of how someone got there. Deps present, real crypto verification, nothing
disabled. Deps genuinely absent, loud failure at boot, naming the fix.
Both states behave exactly like they did before this change for anyone
who already has pyjwt; the only thing that changed is what happens when
it's actually missing, which used to be silence until first login and is
now immediate and unambiguous. I wrote the reasoning directly into
`clerk.py`'s docstring rather than leaving it as a decision only I
remembered making.

## Proving It, Not Just Testing It

The unit tests were the easy half — monkeypatch `_pyjwt_available` false,
construct a `ClerkProvider`, assert the `RuntimeError` names `pip install
'fymo[clerk]'`. The part I didn't want to fake was whether the *real*
crypto path still works once the extra is actually installed, so I added
`pyjwt[crypto]` to the dev dependency group specifically so a real test
could exercise it: generate an actual RSA keypair, sign a real JWT, fake
only the network JWKS fetch (the one thing that would otherwise need a
live HTTPS endpoint), and let the genuine PyJWT/cryptography decode path
run against it, both accepting a valid token and rejecting a tampered one
and a wrong-issuer one.

Then I didn't trust that either, because everything up to that point still
ran inside one dev venv that happens to have everything installed at
once, which is exactly the kind of environment that can't tell you
whether packaging boundaries are real or just accidentally true. Built an
actual wheel with `uv build`, spun up a genuinely clean venv with nothing
in it but fymo's base dependencies, and pointed `FymoApp` at a project
configured for `type: clerk`. It refused to start, naming the install
command, with pyjwt truly absent from `sys.path` — not mocked absent,
actually absent. Then installed `fymo[clerk]` into that same clean venv
and ran it again: booted clean, `ClerkProvider` installed, auth enabled.
That's the sequence the issue actually asked for, and I wanted to have
watched it happen outside the test suite's own bubble at least once
before calling it proven.

## What Didn't Need Solving

OIDC and OAuth got named extras too — `fymo[oidc]`, `fymo[oauth]` — even
though both are pure `urllib` today and need nothing. Tempting to skip
that as premature, but the cost of naming them now is zero and the
alternative is worse: a user reading docs sees `fymo[clerk]` exists and
has no idea whether `fymo[oidc]` is a thing they should also expect, or
whether OIDC just doesn't need one. Naming the whole family now means a
future real dependency for either slots into an extra that already has
the name users would type, instead of introducing a new naming
convention later. Wrote that reasoning down next to the empty extras in
`pyproject.toml` rather than leaving it to look like an oversight.

## The Count

799 passing, 123 skipped, zero failed — the skips are the usual
`node_modules`-not-installed and no-live-Postgres cases this worktree
doesn't have, not anything from this change. Twelve new tests directly
covering the packaging boundary, three more pinning the actual extras
shape in `pyproject.toml`, plus the two from-a-real-wheel boot checks run
by hand outside pytest entirely.

---

*End of Journal Entry 023*
