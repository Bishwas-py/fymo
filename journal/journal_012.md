# Journal Entry 012: Reading My Own Codebase Like a Stranger

**Date**: July 14, 2026
**Focus**: A full audit pass over fymo — dead code, drifted duplicates, and one real dispatch bug the duplicates were hiding
**Status**: Shipped

## Why Bother

Nothing was broken. That's what made this pass different from the last few
entries — no bug report, no silent worker, no hydration mismatch pulling me
in. I sat down and went looking for the kind of rot that never announces
itself: files nobody imports anymore, exception classes nobody raises,
two copies of the same logic that used to be one and quietly stopped being
one. The unglamorous stuff. It took the whole day and touched seven
different corners of the codebase, and the most useful thing it produced
wasn't the cleanup — it was catching a real gap the cleanup accidentally
walked into.

## The Bundler That Time Forgot

`fymo/bundler/` still existed, sitting there with a stray `.pyc` and two
JS runtime bundles from before esbuild took over. I opened
`runtime-metadata.json` expecting a date and got a full path:

```json
"runtime_path": "/Users/bishwasbhandari/Projects/fymo/fymo/bundler/js/dist/svelte-runtime.js",
"build_time": "2026-04-28T07:57:26.377Z"
```

April. Three and a half months of sitting in the repo, `.gitignore`
entry and all, backing a `fymo build-runtime` command that had been a
deprecation-warning no-op since the per-route esbuild pipeline replaced
it. Deleted both, deleted the command, thirteen thousand lines gone in one
commit. Nothing referenced any of it — I checked with a plain grep before
touching anything, because "nothing imports this" is the kind of claim
that's worth being paranoid about once and confident about forever after.

## Exceptions That Were Never Thrown

`TemplateError`, `CompilationError`, `RenderingError`, `AssetError` — all
defined, all imported into places that had `except TemplateError:` blocks
sitting around them, and not one of them ever raised. Tracing why took a
minute: these were guards from before the render path ran through a
subprocess sidecar. Back when template rendering happened in-process,
a compilation failure really was a Python exception you could catch by
type. Once rendering moved to a subprocess and failures started coming
back as structured envelope errors instead, the catch blocks became
permanently unreachable — but nobody deleted them, because an unreachable
`except` clause doesn't fail a test, doesn't throw a warning, doesn't do
anything except sit there looking like it matters. `RouterError` and
`ConfigurationError` stayed; those are genuinely raised and tested
elsewhere. The difference between the two piles was never obvious from
reading a single file — it only showed up once I went looking for every
raise site and found some names simply weren't on the list.

## Two Scaffolds, One Silent Drift

`fymo new` and `fymo init` each hand-wrote their own `fymo.yml` template.
They'd been doing that since early on, and somewhere along the way
`init`'s copy stopped including the `build:` block that `new`'s copy had.
Nobody edited `init.py` and forgot the block — more likely, `new.py` grew
a `build:` section for some later feature and `init.py` simply never got
the memo, because there was no single place that memo could have gone.
Unified both behind one `render_fymo_yml()`. While in there, noticed every
new project also got a `config/routes.py` scaffolded into it that the
router only reads when `fymo.yml` is *absent* — and `new.py` always writes
`fymo.yml` in the same breath. Every generated `config/routes.py` was dead
weight from the moment the project existed. Dropped it too.

## The Ownership Check That Was Written Twice

This is the one that mattered. `fymo`'s remote functions have a rule:
a function is only callable from the browser if it's actually *defined*
in the module it's dispatched through, not merely imported into it — plus
an `__fymo_remote__` marker when explicit opt-in is configured. That rule
existed in two places: `discovery._collect_module_functions`, which builds
the manifest the client SDK is generated from, and
`router._resolve_fn_in_module`, which decides at request time whether to
actually call something. Same rule, two implementations, and they'd
drifted apart in a way I didn't expect: discovery checked
`inspect.isfunction(obj)`, but the router only checked `callable(fn)`.

Those are not the same check. A class instance with a `__call__` method is
callable. It is not a function. Which meant the router would, on a
hand-crafted request naming a module-level object instead of a function,
dispatch it — even though discovery would never have generated client code
for it in the first place, because discovery's stricter check would have
skipped it. The manifest and the dispatcher disagreed about what was
exposed, and the more permissive one was the one actually deciding what
ran.

I wrote a test before touching either file: scaffold a module with an
imported function, an unmarked owned function, a marked owned function,
and a callable class instance — assert discovery's manifest and the
router's dispatch decision agree on all four, in both opt-in states.
Ran it against the original code first to confirm it actually caught the
class-instance gap (it did — the router accepted what discovery would
have refused). Then pulled the shared rule into one function,
`is_exposed_remote_fn()`, had both call sites use it, and watched the same
test turn green for the right reason instead of by accident. That
sequencing mattered more than the fix itself; a test written after the fix
tells you the fix runs, not that it fixes anything.

## The Manifest Lesson, Paid Down Twice

`fymo build` and `fymo dev` each re-derived the same seven-step sequence
before invoking esbuild — hygiene check, route and layout discovery,
client entry generation, global CSS detection, remote and broadcast
codegen, SSR tree composition — diverging only at the actual esbuild
invocation. I'd seen this exact shape of bug before: this is precisely the
duplication pattern that produced the dev-manifest hydration mismatch a
few entries back, the one `manifest_matching.py` got extracted to fix.
Same medicine again — `prepare_build_config()` now owns the whole
pre-esbuild sequence for both commands.

Pulling the two implementations into one function forced me to look at
every line where they differed, and three real behavioral divergences
fell out that had been living separately, unexamined, in two files: the
"node not found" error message has slightly different wording between the
two commands; `fymo build` fails fast with a clear error when route
discovery finds zero routes, `fymo dev` has never had that check and just
proceeds; and `fymo build` catches a `ValueError` from remote-module
discovery (raised for untyped remote-function parameters) and re-raises it
as a clean build error, while `fymo dev` lets the raw `ValueError`
propagate. None of these looked like bugs on their own — more like nobody
had ever needed `fymo dev` to fail as loudly as `fymo build` does, since
you're staring at a running terminal either way. I left all three exactly
as they were and wrote down why, in the same function, instead of fixing
silent divergence by inventing a new one nobody asked for. The point of
this pass wasn't to make build and dev identical. It was to make sure
whatever gap remains between them is a decision, written down in one
place, instead of an accident spread across two.

## Jobs and Broadcasts Had Already Disagreed

Last piece: auth, jobs, and broadcasts each had their own copy of the
same two things — a dotted-path class loader (`"app.mymodule.MyProvider"`
→ the actual class) and the string-or-object provider instantiation logic
around it. Jobs and broadcasts additionally had structural copies of an
`app/<subpackage>/*.py` directory walker, and *that* copy had already
drifted: broadcasts raised on a duplicate channel name defined in two
modules, jobs silently let the second module's function win and threw the
first away.

I don't know when that divergence happened or which one came first. What
I know is that neither behavior was ever a deliberate design call — they
were both just "whatever the walker happened to do" in each subsystem's
own copy-pasted version, and copy-pasted code doesn't stay identical, it
just stays unnoticed. Pulled the walker into
`fymo.core.app_discovery.discover_app_functions()` and made collision
handling a required argument instead of an implicit default, so the two
callers can't quietly disagree again — if a subsystem wants last-wins
behavior, it has to ask for it by name. Jobs now raises
`DuplicateTaskError` instead of silently overwriting, which is a real
behavior change I want to be honest about: someone with two job modules
that happen to define the same function name will see a new failure they
didn't see yesterday. It's the correct failure — silently dropping a
scheduled job because another file happened to reuse its name is worse
than an import-time error naming exactly which two files collided — but
it's still a change, not just a refactor, so it's called out as one.

## What I Left Alone

Auth's three providers — password, OAuth, Clerk — share the same dotted-
path loader now, but I didn't fold them into the same discovery walker as
jobs and broadcasts, because they're not the same shape of problem. Jobs
and broadcasts each pick *one* provider from `app/<subpackage>/*.py` by
convention-based discovery. Auth explicitly configures a *list* of
providers side by side, because a real app wants password login and
Google OAuth live at the same time. Collapsing that into the discovery
walker would have meant bending a genuine one-provider vs. many-provider
distinction to fit a shape that doesn't apply to it, just to make three
subsystems look symmetric on paper. That's not deduplication, that's
forcing a template onto something it doesn't describe.

Same reasoning for the manifest schema, matching, and cache layering —
the code that came out of the earlier hydration bug fix. It's already the
"did it right" example: one schema, one matching function, one cache,
each with a clear reason to be separate from the others. Auditing it
again would have meant either finding nothing (likely) or inventing
something to justify the pass (worse). Proportionate engineering cuts
both directions — it means deleting the dead bundler directory without
agonizing over it, and it means leaving code alone when it's already
doing the one thing it's supposed to do.

## The Count

644 passing, 10 skipped, zero failed — up from 608 at the start of this
pass. The number that mattered more than the total was the one test that
existed specifically to fail against the old code before it could pass
against the new: proof that the router's `callable()` check really would
have dispatched a class instance discovery had already decided not to
expose, and that unifying the two checks actually closed that gap instead
of just making the code shorter.

---

*End of Journal Entry 012*
