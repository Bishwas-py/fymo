# Journal Entry 013: The .env File That Never Existed

**Date**: July 15, 2026
**Focus**: Loading a `.env` file into the process environment, dev-only, before `fymo.yml` gets parsed
**Status**: Shipped

## The Gap

Went looking for something specific this time, not tripping over it by
accident: does fymo load a `.env` file anywhere? It doesn't. `${VAR}`
interpolation in `fymo.yml` reads straight from `os.environ`, which is
correct in production, but means every local session starts with exporting
half a dozen variables into the shell by hand before `fymo dev` resolves
anything. Clone a project, open a new terminal, forget you did that
yesterday, watch `fymo.yml` blow up with "references undefined environment
variable." Not a bug exactly. Just friction nobody had gotten around to
fixing.

The open question was whether to hand-roll a parser or pull in
`python-dotenv`. Checked what the codebase already does with optional
dependencies before deciding: `pyjwt[crypto]` is used for Clerk token
verification, and it's not even in `pyproject.toml` — it's a bare `import
jwt` inside a `try/except ImportError` that only fires if you actually
exercise Clerk auth. That's the house style: core stays dependency-free,
anything not needed by every install is either declared optional or lazily
imported with a clear failure message. `.env` parsing is fifteen lines of
`KEY=value`, comments, and quote-stripping. Adding a dependency for that
would have been the wrong kind of consistency — consistent with what other
frameworks do, inconsistent with what this one already does.

## Where It Actually Has to Go

The interpolation itself lives in `config.py`, resolved on the raw YAML
text before `yaml.safe_load` ever sees it. So the loader has to run before
`ConfigManager` gets constructed, not before `fymo.yml` gets read — those
aren't the same moment, and `ConfigManager.__init__` does both back to
back. `FymoApp.__init__` resolves `self.dev` and then builds a
`ConfigManager` thirty-some lines later in the same function. That gap is
exactly where the load needs to sit: after `dev` is known, before config
parsing starts.

There's a second place `ConfigManager` gets built: `fymo jobs-worker`, its
own OS process, separate from the web app entirely. And it had a real
ordering problem already, unrelated to `.env` — it constructed
`ConfigManager` first and only figured out `dev` nine lines later, purely
for a logging call. Nobody had ever needed dev-mode to be known before
config parsing there, so nobody noticed the ordering was backwards. Adding
`.env` support meant fixing that ordering too, otherwise the worker would
be the one place `.env` quietly didn't work, which is precisely the kind
of inconsistency the original bug report was about in the first place.

One thing I deliberately didn't try to fix: `FYMO_DEV` itself only ever
comes from a real environment variable, read before `.env` loads. You
can't put `FYMO_DEV=1` in `.env` and have it flip a process into dev mode,
because by the time anything would read `.env`, it's already decided
whether it's allowed to. That's not an oversight, it's the only ordering
that isn't circular — checking `.env` to decide whether to read `.env`
doesn't have a sane answer. Wrote it down as a known limitation instead of
quietly working around it with something clever, because the clever
version would have been a chicken-and-egg bug wearing a feature costume.

## What Constructing a FymoApp in a Test Actually Costs

Wanted a test proving that a value loaded from `.env` really does flow
through to `${VAR}` interpolation in `fymo.yml`, not just that `os.environ`
gets populated. Building a real `FymoApp` for that turned out to need more
than a `.env` file and a `fymo.yml` — the constructor unconditionally wants
`dist/sidecar.mjs` to exist and raises a clean `RuntimeError` if it
doesn't, no dev-mode bypass. `test_logging.py` had already solved this by
hand-rolling the smallest possible sidecar stub, just enough of the
length-prefixed JSON protocol to answer a startup ping. Reused the same
stub rather than inventing a second way to fake the same thing. For the
two tests that only needed to check whether `os.environ` got touched, I
skipped the stub entirely and let the `RuntimeError` happen — `.env` loads
early enough in `__init__` that the assertion still holds true by the time
construction fails later for an unrelated reason.

## The Test That Would Have Passed Either Way

Got this one wrong on the first pass and a review caught it before it
shipped. The `jobs-worker` test asserted that a `.env` value ended up in
`os.environ` after calling `run_jobs_worker` — true, but it would have
been just as true if `.env` loaded *after* `ConfigManager` instead of
before. The assertion didn't actually depend on the ordering it was named
after. Fixed it by making `fymo.yml` require the `.env`-provided variable
through `${VAR}` interpolation: if the ordering were ever wrong, config
parsing would raise `ConfigurationError` instead of the worker's normal
`SystemExit(1)`, and the test would fail on the wrong exception type.
Didn't just trust that reasoning — reverted the ordering fix by hand for a
minute, watched the test fail with exactly the `ConfigurationError` it was
supposed to catch, then put the fix back. A test that can't fail isn't
testing anything, it's just decoration that happens to be green.

## What's Still Manual

Fymo doesn't add `.env` to a new project's `.gitignore` for you. Scaffolding
and the loader are separate concerns, and `fymo new`'s gitignore template
not knowing about `.env` yet is a small, honest gap rather than something
this change should have quietly absorbed. Worth a follow-up, not worth
blocking on.

Also ran into issue #26 while tracing where `dev` gets decided: `fymo dev`
doesn't actually pass `dev=True` today, it falls through to whatever
`FYMO_DEV` happens to be in the shell. That's a real, separate problem —
once it's fixed, `.env` loading here will just start working for `fymo dev`
without either issue having to know about the other, since both key off
the same `self.dev`. Left it alone. Not every gap you notice while working
is a gap you should be the one to close today.

---

*End of Journal Entry 013*
