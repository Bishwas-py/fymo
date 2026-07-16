# Journal Entry 020: A Pathname That Refused to Update

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

## Where It Landed

```js
import { route } from '$route';
$effect(() => {
  console.log(route.pathname, route.params);
});
```

Reactive on every soft nav, no listener to wire up, no cleanup to forget.
Full suite: 883 passing, 10 skipped, up from before this pass started.

---

*End of Journal Entry 020*
