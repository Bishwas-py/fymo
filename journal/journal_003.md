# Journal Entry 003: Killing the Per-Request Compiler - Build Pipeline + Node Sidecar

**Date**: April 28, 2026
**Focus**: Replacing regex/eval SSR with a real build pipeline and a persistent Node sidecar
**Status**: ✅ Shipped

## The Breaking Point

The old SSR path finally annoyed me enough to rip it out. What we had was
honestly a science experiment: every single request spawned a Node subprocess
to compile the Svelte component, spawned a second one to bundle whatever npm
packages the page imported, regex-rewrote both the source and the compiled
output, then eval'd the result inside STPyV8.

It worked. Mostly. But I hit three bugs in one sitting and all of them lived
on the same fault line:

1. A bare `'node'` in the esbuild flags silently killing a bundle
2. A `dev: true` mismatch between compiler and runtime
3. The FILENAME extractor not handling the `export default function` form

Every one of them was a regex/eval boundary issue. When three unrelated bugs
share an architecture, the architecture is the bug.

## What Else Was Wrong

- **STPyV8 has no Node APIs.** No `fs`, no `path`, no `Buffer`, no `fetch`.
  Any npm package touching them broke at SSR time with useless errors. It
  also had no Python 3.14 wheels, so the venv was broken on first install.
- **95 KB todo page.** The entire date-fns bundle was inlined twice (loader
  plus module string), plus component sources as escaped strings executed
  with `new Function`. For a todo list.
- **Zero browser caching.** Every page reshipped every byte.
- **Slow.** Every GET recompiled Svelte and rebundled npm from scratch.

## The New Shape

Two ideas: compile at build time, render in a long-lived process.

```
app/templates/*.svelte ──(fymo build: esbuild + svelte plugin)──▶ dist/
                                                                   ├── ssr/<route>.mjs
                                                                   ├── client/<route>.<hash>.js
                                                                   ├── client/chunk-<name>.<hash>.js
                                                                   ├── sidecar.mjs
                                                                   └── manifest.json
```

`fymo build` walks `app/templates/`, treats each `index.svelte` as a route
entry, and runs esbuild twice. The server pass (`generate: 'server'`)
produces `dist/ssr/<route>.mjs`. The client pass runs with
`splitting: true` and hashed filenames, so date-fns imported by five pages
becomes one chunk the browser downloads once and caches forever.

At runtime, a single persistent Node process (the sidecar) boots alongside
the Python app, imports the compiled SSR modules, and talks to Python over
stdio JSON. Request comes in, the controller computes props, Python sends
`{route, props}`, the sidecar answers `{body, head}`, and Python wraps it in
a small HTML shell with hashed script and css links.

The division of labor ended up beautifully clean:

| Concern                   | Lives in            | Runs when   |
|---------------------------|---------------------|-------------|
| Svelte compilation        | esbuild plugin      | build only  |
| NPM resolution & bundling | esbuild (splitting) | build only  |
| SSR engine                | Node sidecar        | per request |
| Hydration                 | hashed client JS    | browser     |
| Routing & data            | Python controller   | per request |

## Results

- Todo page HTML: ~95 KB → under 10 KB
- Any npm package that runs in Node 18+ now works in SSR
- Hashed bundles cache properly across deploys
- The regex/eval layer is just... gone

## What I Deliberately Didn't Do

File-based routing (the YAML routing stays), layouts, HMR with state
preservation (full-page reload over a small SSE channel is fine), streaming
SSR, deploy adapters. Each is its own project. None of them block the core
win.

## Lesson

The app-author surface didn't change at all. Same `app/templates/*.svelte`,
same `app/controllers/*.py`, same edit-save-refresh loop. That constraint is
what made the rewrite safe to do in one go: if a todo app renders
identically before and after, the internals were free to change completely.

---

*End of Journal Entry 003*
