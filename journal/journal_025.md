# Journal Entry 025: The Bug That Only Exists Outside This Repo

**Date**: July 16, 2026
**Focus**: Two filed issues about a fresh `pip install` never being able to build, and a third bug the fix itself surfaced
**Status**: Shipped

## The Report I Couldn't Reproduce at First

Two issues came in close together, filed by the same person, about the
same symptom from two different angles. #55: a brand new `fymo new`
project's `package.json` only listed `svelte` and `esbuild`, so
`npm install` never pulled in `esbuild-svelte` or `svelte-preprocess`,
and `fymo build` died immediately looking for a module that was never
going to be there. #60 was the uglier one: even handed a project whose
`node_modules` was already complete and known-good, `fymo build` still
failed, but only if fymo itself was a real `pip install`. Inside this
monorepo, building anything just worked, every time, no matter what I
tried to break.

That last part should have been the whole investigation right there.
Something that only breaks outside the repo it was written in is never
really about the code you're staring at — it's about where that code
happens to live on disk.

## Why the Repo Itself Was Lying to Me

`fymo/build/js/build.mjs` opens with `import { build } from 'esbuild'`.
Perfectly normal-looking line. The part that doesn't show up by reading
it is *how* Node resolves that: it walks up from the importing file's own
directory, never from the project being built, never from wherever the
process happens to be running. Inside this repo, `fymo/build/js/` sits
underneath the repo root, and the repo root has its own `node_modules`
with `esbuild` in it. So the bare import always found something. It just
never found the *right* something on purpose — it found it by geographic
accident, because this repo's own dev dependencies happened to sit as an
ancestor of the file doing the importing.

Move that same file into `site-packages/fymo/build/js/`, which is exactly
where a real `pip install` puts it, and that ancestor walk runs out of
directories to check long before it reaches anything with `esbuild` in
it. Doesn't matter how correct the target project's own `node_modules`
is. The import was never looking there.

The fix pattern already existed a few lines down in the same file, for a
completely different reason. `esbuild-svelte` and `svelte-preprocess` get
resolved through `createRequire` pointed at the *project's* own
`package.json`, so the Svelte version doing the compiling matches the one
running at SSR time. Nobody had ever needed to do the same thing for
`esbuild` itself, because inside this repo it was never actually broken.
Extended that same resolution to `esbuild`, in both `build.mjs` and
`dev.mjs` — `dev.mjs` imports it as a namespace instead of a single named
export, so its version pulls in the whole module object instead of just
destructuring `build` off it, but otherwise it's the identical move.

## Writing a Test That Couldn't Cheat

The dangerous thing about this bug is that almost every existing test in
this suite runs against the repo's own editable checkout, which means
almost every existing test would keep passing right through this bug
without ever noticing it, for the same reason I didn't notice it at
first. A regression test that exercises the source tree from inside this
repo proves nothing here.

So the fast test copies `fymo/build/js/` out to a scratch directory with
no `node_modules` anywhere above it — a pytest tmp dir genuinely has
none — which stands in for a real install location honestly, not just in
name. Pointed it at a project directory whose only copy of `esbuild`
lives in its own `node_modules` (reused from `examples/blog_app`, already
installed, rather than a real `npm install`). Ran the original code
against that setup first, on purpose, before writing the fix: it failed
with the literal `Cannot find package 'esbuild'` error from the bug
report. Then applied the fix and watched the same test turn green for the
same reason it had just gone red.

## The Second Bug the First Fix Walked Into

Fixing `esbuild`'s own resolution felt like the whole job. It wasn't. I
ran the actual quick start end to end to make sure — real wheel, real
scratch venv, real `pip install`, `fymo new`, symlinked-in known-good
`node_modules`, `fymo build` — and it still failed. Different error this
time: `Could not resolve "svelte/store"`.

That import lives in `fymo/build/js/runtime/route.js`, the file behind
`$route` (which I'd written about in the previous entry, for a completely
unrelated reason — a store instead of `$state`, specifically to avoid two
disconnected copies of Svelte's runtime getting bundled). `route.js` also
ships inside fymo's own package, not the project's. And esbuild's own
bundler resolves a bare import inside a file it's bundling by walking up
from that file's directory, the exact same algorithm Node just used to
break the first time. Same disease, different organ. `createRequire`
couldn't touch this one — that machinery only helps imports Node itself
evaluates, and this import is resolved by esbuild's bundler while it's
turning `route.js` into part of somebody else's built output.

The fix was esbuild's own equivalent of `NODE_PATH`: a `nodePaths` option
telling it where to look once its normal directory walk comes up empty,
pointed at the project's `node_modules`. Added it to all four
build/context calls across `build.mjs` and `dev.mjs`, since both the
server and client passes touch `$route`. Wrote the failing test the same
way as the first one — a route that imports `$route`, built from outside
the repo's own `node_modules` ancestry, watched it fail with the real
error, then watched it pass.

I hadn't planned to touch this file. It only turned up because I ran the
actual end-to-end flow instead of stopping once the two tests I'd
already written went green. If I'd stopped there, the smoke test the
issues themselves were asking for would have kept failing for a second,
completely different reason, and I'd have called the job done with the
documented quick start still broken.

## The Version Numbers I Didn't Actually Check

Independent review caught something smaller but real: the scaffold fix
for #55 added the missing `devDependencies` correctly, but left `svelte`
and `esbuild`'s existing version pins untouched — `^5.38.0` and
`^0.25.0` — while claiming, in both the commit message and a test
docstring, that the scaffold now matched `examples/blog_app/package.json`
exactly. It didn't. Blog_app pins `^5.56.4` and `^0.25.9`. I'd read the
right file earlier in the investigation and then just... didn't carry the
two numbers that were already present over, only the ones that were
missing. Caret ranges mean this was never going to break anyone's actual
`npm install`, but the diff said one thing and did another, and that gap
was worth closing on its own, not waved off because the practical
consequence happened to be zero.

## Closing the Loop for Real

Built a real wheel with `uv build`, installed it into a scratch venv that
had never heard of this repo, ran that venv's own `fymo new`, symlinked
in `examples/blog_app`'s working `node_modules`, ran that venv's own
`fymo build`. Manifest, sidecar, both SSR and client output, all there,
nothing masked by this repo's own directory layout. Also ran a real
`npm install` against the freshly-scaffolded project by hand, once,
outside the test suite: fifty packages, zero missing, both dependencies
that were absent before now present. Turned that same wheel-build-and-
install sequence into a standing test, symlinking rather than running a
live `npm install` in CI so it stays fast and doesn't depend on having a
network connection every time the suite runs.

Three commits: the scaffold fix, the resolution fix, the end-to-end test,
plus a fourth once review caught the version-pin miss. Full suite: 902
passing, 10 skipped, same 10 that were already skipped before I touched
anything — a couple of provider tests that need a real Postgres instance
sitting somewhere and want nothing to do with this.

---

*End of Journal Entry 025*
