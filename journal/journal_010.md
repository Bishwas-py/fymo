# Journal Entry 010: Layouts, a Reactive Router, and Closing the Import Free-For-All

**Date**: July 13, 2026
**Focus**: Root/resource `_layout.svelte`, a reactive soft-nav router that stops remounting the page, global CSS, then `$lib`/`$_shared` aliases and a server-only boundary
**Status**: ✅ Shipped

## The Complaint

Every page in the blog example started with the same two lines:

```svelte
import Nav from '../_shared/Nav.svelte';
...
<Nav />
```

Three pages, three copies. Add a footer tomorrow and it's three edits, not
one. Fymo had controllers, remote functions, auth providers — a real
framework — and no answer for "wrap every page in the same shell." Every
other SSR framework worth comparing to solved this years ago. Time to fix
it.

Worse, digging into the client runtime, soft-nav wasn't actually soft. Every
navigation ran `unmount()` on the whole page and `mount()`-ed a fresh one,
Nav included. So even without shared layouts, every click was already
paying to rebuild markup that hadn't changed. Fixing layouts without fixing
that would just be new wrapper markup getting torn down and rebuilt on
every click — half a fix.

## The Shape of It

Two conventions, mirroring the existing controller/template split:

```
app/templates/_layout.svelte           # root, optional
app/templates/posts/_layout.svelte     # per-resource, optional
app/controllers/_layout.py             # root layout data, optional
```

A layout is just a component with a `children` snippet:

```svelte
<script>
  let { children } = $props();
</script>
<Nav />
{@render children()}
```

Root plus one level of per-resource nesting, nothing deeper — routing
itself is still flat, so going further would mean inventing a routing
rewrite nobody asked for.

The interesting part was the client. Instead of hand-rolling a diff
algorithm to figure out which part of a layout chain changed between two
routes, I leaned on the compiler: hold the leaf and the resource layout in
`$state`, mount once, and let Svelte's own reactivity swap components when
the reference changes. `<svelte:component>` doesn't even exist anymore in
runes mode for exactly this reason — a variable holding a component just
works as a tag. Navigating within the same resource layout now touches
nothing above the leaf. Navigating across resources swaps exactly the
piece that changed, and nothing else remounts.

## Two Bugs the Test Suite Couldn't See

Everything passed. Discovery, manifest, controller merging, the build
pipeline, soft-nav payloads — all green, 539 tests. Then one more pass
before calling it done, and two real problems turned up that no unit test
had a chance of catching, because none of them execute a browser.

First: the generated client bundle for a layout route never re-exported
its leaf component as `default`. The soft-nav router does
`import(leaf.module).default` to grab the next page's component — and
`default` was `undefined`. Every single navigation from a layout route was
silently falling back to a full page reload. The entire point of the
rewrite, dead on arrival, and every Python test happily passed because none
of them import the compiled JS and click anything.

Second, and sneakier: the server-rendered tree and the client's hydrate
target weren't actually the same shape. The server side rendered a plain,
unconditional nesting; the client side wrapped the same content in an
`{#if}`/`{:else}` block (so it could later swap in a resource layout that
wasn't there on first load) plus a `<svelte:boundary>` around the leaf.
Same visible HTML, different compiled anchors underneath — exactly the
kind of mismatch that makes `hydrate()` quietly give up and remount from
scratch, eating the performance win before a single click happens. Fixed
by making the server side use the identical snippet-and-conditional shape,
just with the condition hardcoded to a literal instead of reactive state,
so both sides emit the same anchors regardless of which branch is live.

Confirmed both fixes by actually compiling the generated files through the
real compiler and reading the output — not just trusting that the build
didn't error, since it hadn't errored the first time either.

## Global CSS, the Boring Part

The last piece was smaller: an optional `app/templates/_global.css` that
gets its own esbuild entry point, so it emits one hashed file linked on
every page instead of the per-route CSS extraction duplicating shared
rules across bundles. Fymo doesn't vendor Tailwind or PostCSS for this —
it just gives you one real, cacheable stylesheet slot, and whatever CSS
tool you already like plugs into it the normal way, by writing plain CSS
to that path before the build runs.

## The Import Rabbit Hole

Migrating the blog to the new layout meant touching `Nav.svelte`, which
still had `import { user, ready, logout } from '../../lib/auth'`. Relative
paths like that get worse every time a file moves. Poked at whether
`app/components/` (a leftover, unused scratch directory sitting in the
todo example) actually worked as an import target, out of curiosity more
than anything. It did — built clean, rendered for real, `date-fns` and all.
Turns out nothing about fymo's own directories was ever special; esbuild
resolves relative imports through the filesystem same as any bundler, and
`_shared/` only ever worked because nothing treats it as a route, not
because it's a blessed location.

So: formalize `$lib` and `$_shared` as real aliases instead of pretending
one convention is safer than any other directory name. Turns out
`tsconfig.json`'s `paths` field already had a precedent sitting right
there — the remote-function codegen uses `$remote/*` — and esbuild honors
`paths` natively, no plugin required, since the alias targets are ordinary
files that already exist on disk.

But formalizing a `$lib` alias people will actually reach for changes the
risk profile. Nothing stops server-only code — a secret, a DB helper —
from ending up under `app/lib/` and getting pulled into the client bundle
by accident, the same way SvelteKit ran into this years ago and answered
it with `$lib/server`. So: `app/lib/server/**` is now a hard build failure
if the client bundle ever reaches it, enforced with an esbuild plugin
scoped tightly enough that it costs nothing when the directory doesn't
exist at all. Proved it both ways — planted a fake secret file, imported
it from a client component, watched the build die with a clear message
naming the file; then removed the import and watched the build go green
again, so the guard isn't just a landmine that fires on the wrong thing.

## What Stuck

The lesson that'll outlast this specific feature: a green test suite means
nothing about a path that suite never exercises. Every layout bug that
actually mattered here was invisible to Python-level tests because they
never execute the compiled JavaScript — the fix wasn't more tests in the
same style, it was tracing the actual generated output by hand and
confirming what a browser would really do with it.

---

*End of Journal Entry 010*
