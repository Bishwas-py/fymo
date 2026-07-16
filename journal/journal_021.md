# Journal Entry 021: A Pathname That Refused to Update

**Date**: July 16, 2026
**Focus**: A reactive route/params primitive for the client, since location.pathname never was one
**Status**: Shipped

## The Effect That Never Ran Twice

The report was small and easy to reproduce: an `$effect` reading
`location.pathname` to log the current path never fired again after a soft
navigation. First instinct was to call it a framework bug. It wasn't.
`location.pathname` is a plain DOM property. Svelte's `$effect` only
re-runs when something it read was actually reactive, a rune or a store,
and `window.location` is neither. The effect ran once, captured whatever
the path was at that moment, and never looked again. Nothing about that is
fymo's fault. But going looking for what fymo offers instead of it turned
up nothing, and that part was.

`getDoc()` looked like it might work and doesn't, for the exact same
reason: it's a closure variable reassigned on every navigation, not a
tracked signal. The only thing that actually fires on a soft nav is a
`fymo:navigate` CustomEvent, which means every component that cares about
the route has to hand-roll its own `$effect` plus `addEventListener` plus a
local `$state` plus cleanup. That's boilerplate a framework should own.

## The Gap Under the Gap

Digging further turned up a second problem sitting under the first one.
Dynamic route segments, the `:id` in `/posts/:id`, get matched server-side
in `Router.match()` and threaded into the controller's `getContext(params)`
call. But they never became their own field anywhere the client could read
them directly. A controller had to choose to echo its own params back into
props for the client to ever see what was matched. There was no
guaranteed, framework-owned way to answer "what were the params for this
navigation," only an accident of whether a specific controller happened to
return them.

## What Had to Be True First

Before writing anything I needed two facts, not assumptions. First:
whether `fymo build`'s esbuild output shares one runtime chunk across every
route or duplicates the Svelte runtime per route bundle, since a
`$state`-backed shared module across a soft nav to a different route's
bundle only stays reactive if both bundles are running the same signal
tracking instance. It does share one chunk, confirmed by building a real
app and grepping the output: the reactive object's default value showed up
exactly once, in one shared chunk, not once per route.

Second: whether `esbuild-svelte`'s plugin actually compiles a plain
`.svelte.js` module (needed to legally call `$state()` outside a
component), or only real `.svelte` files. Reading the plugin's source
directly instead of guessing turned up something I hadn't expected: for
Svelte 5 specifically, its default filter already matches `.svelte.js` and
`.svelte.ts`, same convention SvelteKit uses for shared reactive modules.
No build config change needed, just naming the file correctly.

## Building It

The params field was the easy, mechanical half: one new key in the
soft-nav JSON envelope, one new script island on the initial page load,
both fed from the exact same `Router.match()` result that already existed.
The harder half was the client object itself, a static file shipped inside
fymo (its content never varies per app, so no reason to generate it per
project the way remote and broadcast codegen does), resolved through a new
`$route` virtual import that mirrors the existing `$remote`/`$broadcast`
convention rather than inventing a new one. Query string got included too,
since it needs zero server involvement, the client already knows
`location.search` at nav time. Leaf id got left out for now, easy to add
later without breaking anything, since the object is additive.

One decision I made deliberately rather than by accident: the reactive
route state is seeded correctly before `hydrate()` runs, so anything read
inside `$effect` or an event handler is right from the first paint onward,
but it isn't threaded into the actual SSR render pass. Doing that safely
would have meant changing the Python-to-Node sidecar's wire protocol too,
a separate, bigger change. A component that reads route state directly in
top-level markup during the very first render, instead of inside an
effect, could see a brief difference between what the server rendered and
what the client seeded. Params needed for correct SSR output already have
a safe path: the controller's own `getContext(params)`, unchanged by any of
this.

## The Test That Caught the Real Bug

Wired the plugin into `build.mjs`, ran the whole suite, everything passed.
Should have been suspicious of that. `fymo dev` doesn't use `build.mjs` at
all, it has its own separate esbuild context in `dev.mjs`, a duplication
this codebase has hit before (the exact same shape of bug that got fixed
in an earlier pass over the build/dev pipeline). Two dev-orchestrator tests
failed on the full run: a manifest that never got written within the
timeout. Traced it down to `dev.mjs` never resolving `$route` at all,
which meant every single dev build was failing silently, no error printed
anywhere, just an empty log and a manifest that would never appear no
matter how long you waited.

Fixed it by wiring the same plugin into `dev.mjs`'s two esbuild passes, then
wrote a dedicated test for exactly this seam: build a real app through
`DevOrchestrator`, wait for the manifest, then check that a built chunk
actually contains the route runtime's state. Reverted the `dev.mjs` fix
just to watch that new test fail for the right reason before putting the
fix back. It did, cleanly, the same missing-resolution failure mode as the
original bug. That's the test that would have caught this before it ever
reached anyone running `fymo dev` locally.

## The Bug Every Test Missed

Everything above passed. Full suite green, the new dev.mjs test caught its
bug and stayed caught, a structural check confirmed the reactive object's
default value showed up exactly once in the built output, not duplicated
per route. By every check I had, this was done. So I opened a real browser
instead of trusting that.

Built the blog example for real, added a small debug line to its root
layout, the one component that stays mounted through every soft nav
instead of getting swapped: an `$effect` logging the route on every run,
with an explicit counter so I couldn't fool myself about whether it had
actually re-executed or just showed a value that happened to already be
right. Loaded the page. Counter said 1, value correct. Clicked a link to a
post. URL changed, page content changed, everything looked like a normal
soft nav. Counter still said 1.

Not "showed the wrong value." Never ran again. I mutated the route object
by hand from the browser console, same result: the value on the object
changed, provably, I could read the new value back off it immediately.
The effect just never noticed. Whatever I'd built, it wasn't reactive at
all, it was a shared bucket that happened to hold the right data with
nothing watching it.

## Two Copies of the Thing That's Supposed to Be One

Traced it by reading the actual bytes of the built output, not the source,
the built output. Svelte's own internal reactivity machinery, the code
that creates a signal and the code that notifies whoever's reading it, was
bundled twice, into two different files, completely disconnected from
each other. One copy backed the object my route module created. A
different copy backed the effect tracking inside the layout component. My
mutation updated one graph. The layout's effect was subscribed to the
other. Neither side was broken on its own; they just weren't talking.

The reason took a bit to run down: Svelte's compiler has two separate
code-generation paths, one for ordinary `.svelte` components, a different
one for the `.svelte.js` "module" files the reactive-state pattern I'd
used depends on. In this exact build, those two paths ended up emitting
imports that resolved to two different, un-deduplicated bundles of the
same runtime. My earlier "does the file appear only once" check had been
checking the wrong thing entirely. It confirmed my own small file wasn't
duplicated. It said nothing about whether the actual reactivity engine
underneath it was, and it was.

Once I knew what to look for, checking became trivial: one particular
error message Svelte's runtime carries, a string that survives minifying
because it's used at runtime and not just a source comment, showed up in
two separate files instead of one. That was the whole bug, confirmed in a
single grep once I knew which two files to compare.

## The Fix Was Smaller Than the Bug

Swapped the `.svelte.js`/`$state` pattern for a plain `svelte/store`
`writable`. A store isn't special-compiled where it's defined at all,
nothing about creating one asks the compiler to pick a code-generation
path; only the `$store` shorthand used inside a component that *reads* it
goes through compilation, and that's the same, unremarkable path this
app's own auth state (`user`, `ready` in app/lib/auth.ts) already uses
successfully in this exact build. No special module type, no duplicated
runtime possible, because there was never a second code path for it to
diverge through in the first place.

Rebuilt, same debug layout, same real browser. Counter went 1, clicked,
counter went 2, correct path, correct params, visible in the actual page
text. Clicked again, back to the previous route, counter went 3,
everything cleared correctly. Did it twice more to be sure it wasn't
something timing-dependent that happened to line up once.

This time I didn't just trust that and move on. Wrote an automated
version of the exact same check: build a real app with a temporary
component that reads the route state into visible text, boot the actual
compiled bundle in a real DOM environment, call the framework's own
navigation-update function directly, and assert the text changed. Then,
specifically to prove the test wasn't just passing by accident, I put the
old broken version back, temporarily, and watched that same test fail,
for the right reason, the runtime genuinely duplicated across two files
exactly like it had in the browser. Put the fix back, watched it pass
again. Added a second, cheaper test that just checks for that duplication
directly, so a future change that reintroduces this exact mistake gets
caught in milliseconds instead of needing a browser at all.

Also cleaned up something the rewrite made obvious once it existed: the
seed-and-update logic had been copied inline into both client bundle
templates, four times total. Pulled it into two small functions the route
module itself exports, `seedRoute()` and `applyRouteNav()`, so the
templates just call them. One place owns the mutation now, not four
copies of the same three lines that could quietly drift apart later.

## Where It Landed

```js
import { route } from '$route';
$effect(() => {
  console.log($route.pathname, $route.params);
});
```

The dollar sign in front of `route` matters now: it's a store, not a
rune, so a component reads it through Svelte's ordinary auto-subscription
syntax. Reactive on every soft nav, no listener to wire up, no cleanup to
forget, and this time actually watched it work, more than once, in a real
tab, before calling it done. Full suite: 885 passing, 10 skipped.

---

*End of Journal Entry 021*
