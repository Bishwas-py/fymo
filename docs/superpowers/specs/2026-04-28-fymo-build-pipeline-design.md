---
title: Fymo build pipeline + Node sidecar SSR
date: 2026-04-28
status: approved-design
authors: Bishwas, brainstormed with Claude
---

# Fymo build pipeline + Node sidecar SSR

## 1. Context

Today's Fymo SSR works by:
- compiling Svelte components on every request via a Node subprocess (Python `subprocess.run` per request),
- bundling each NPM package independently via a second `npx esbuild` subprocess per request,
- regex-rewriting both the Svelte source (to replace NPM imports) and the compiled output (to extract component names, strip `export default`, remove `import`),
- evaluating the result inside STPyV8 (a Python binding for V8) plus injecting sub-components via more eval-of-string,
- inlining the entire client runtime (~1MB), every NPM bundle, every sub-component source as escaped strings, and a duplicated hydration boilerplate into the HTML response of every page.

This causes:

1. **Brittle regex/eval pipeline.** Three independent bugs were traced this session: bare `'node'` in the esbuild flags (silent bundle failure), `dev: true` mismatch between compiler and runtime, and `export default function` form not handled by the FILENAME extractor. Each was a regex/eval boundary issue.
2. **Limited library support.** STPyV8 has no Node APIs (`fs`, `path`, `Buffer`, `fetch`, streams). Any NPM package that touches them silently breaks at SSR time. STPyV8 also lacks Python 3.14 wheels (the venv was broken on first install).
3. **Huge HTML responses.** A todo page renders ~95 KB of HTML containing the full date-fns bundle inlined twice (loader + module string), the entire Svelte client runtime references, and component sources as escaped strings executed with `new Function`.
4. **No browser caching.** Every page reships every byte. `<script type="module" src="/assets/svelte-runtime.js">` is the only cacheable piece, and that one was broken (served as a 42-byte stub) until this session's fix.
5. **Slow per-request path.** Every GET re-spawns Node, re-compiles Svelte, re-bundles NPM, re-evals the runtime in V8.

This spec replaces that path with a build-time pipeline + a persistent Node sidecar for SSR. App-author surface (`app/templates/*.svelte`, `app/controllers/*.py`) is unchanged.

## 2. Goals & non-goals

**Goals:**
- Minimal HTML response (target: < 10 KB for the todo example, vs. ~95 KB today).
- Browser-cacheable JS and CSS bundles, hashed for safe long-cache.
- Cross-route shared chunks (date-fns imported by N pages bundles to one chunk, downloaded once).
- Any NPM package that runs in Node 18+ works in SSR.
- Build-time only: all compilation happens during `fymo build` or `fymo dev` (incremental). No per-request compile.
- Same DX as today for app authors: edit `.svelte`, save, refresh.

**Non-goals (this spec):**
- File-based routing (today's YAML-based routing stays).
- Layouts / nested routes.
- TypeScript preprocessor.
- HMR for component state preservation (full-page reload via SSE is acceptable).
- Production deploy adapters (Cloudflare/Vercel/etc.) — out of scope.
- Streaming SSR.
- Service workers / PWA.

## 3. Architecture

```
┌──────────────────┐  fymo build / fymo dev (esbuild + svelte plugin)
│ app/templates/   │ ──────────────────────────────────────────────▶
│   *.svelte       │
└──────────────────┘
                                 ┌──────────────────────────────────┐
                                 │ dist/                            │
                                 │   ssr/<route>.mjs   (server)     │
                                 │   client/<route>.<hash>.js       │
                                 │   client/<route>.<hash>.css      │
                                 │   client/chunk-<name>.<hash>.js  │
                                 │   sidecar.mjs                    │
                                 │   manifest.json                  │
                                 └──────────────────────────────────┘
┌──────────────────┐                       │
│ app/controllers/ │   per request         │
│   *.py           │ ──────────────────────┤
└──────────────────┘                       ▼
                            ┌──────────────────────────────────┐
                            │ Python WSGI app                  │
                            │  router → controller → props     │
                            └──────────────────────────────────┘
                                           │
                                           │  stdio JSON ({route, props})
                                           ▼
                            ┌──────────────────────────────────┐
                            │ Node sidecar (long-lived)        │
                            │  imports dist/ssr/<route>.mjs    │
                            │  calls render(props)             │
                            │  returns {body, head}            │
                            └──────────────────────────────────┘
                                           │
                                           ▼
                            ┌──────────────────────────────────┐
                            │ HTML response (< 10 KB):         │
                            │  <head> {head} <link css>        │
                            │   <link modulepreload>           │
                            │  <body>                          │
                            │   <div id=svelte-app>{body}</div>│
                            │   <script id=svelte-props>…      │
                            │   <script type=module src=…>     │
                            └──────────────────────────────────┘
```

**Five separations of concern:**

| Concern                  | Lives in                                       | Runs when     |
|--------------------------|------------------------------------------------|---------------|
| Svelte compilation       | esbuild + svelte plugin                        | build only    |
| NPM resolution & bundling| esbuild (with `splitting: true`)               | build only    |
| SSR engine               | Node sidecar process                           | per request   |
| Hydration                | Hashed `.js` in `dist/client/`                 | browser       |
| Routing & data           | Python controller (unchanged)                  | per request   |

## 4. Build pipeline

### 4.1 Discovery

`fymo build` walks `app/templates/`. Every `index.svelte` directly under `app/templates/<route>/` is treated as a **route entry**. Components reachable only via Svelte imports from a route are not entries; they're bundled into their parent route automatically by esbuild.

Route name = directory name. `app/templates/todos/index.svelte` → route `todos`.

### 4.2 Server pass

For each route entry, run esbuild once with the svelte plugin (`generate: 'server'`):

```js
await esbuild.build({
  entryPoints: { todos: 'app/templates/todos/index.svelte', home: 'app/templates/home/index.svelte' },
  outdir: 'dist/ssr',
  outExtension: { '.js': '.mjs' },
  format: 'esm',
  platform: 'node',
  bundle: true,
  splitting: false,        // server bundles are per-route only; no shared chunks
  minify: true,
  sourcemap: 'linked',
  plugins: [sveltePlugin({ generate: 'server', dev: false })],
  external: [],            // bundle everything for self-contained SSR modules
});
```

Each emitted `dist/ssr/<route>.mjs` exports the route's component as `default`. The sidecar imports it via dynamic `import()`.

Why platform: 'node': lets `fs`, `path`, `Buffer`, `fetch` (Node 18+), streams resolve to Node built-ins. Any NPM package that uses them works.

Why minify on the server bundle: it's loaded once per process at first request; smaller bytes = faster cold start.

### 4.3 Client pass

One esbuild call with all routes as entry points and splitting enabled:

```js
await esbuild.build({
  entryPoints: { todos: '.fymo/entries/todos.client.js', home: '.fymo/entries/home.client.js' },
  outdir: 'dist/client',
  format: 'esm',
  platform: 'browser',
  bundle: true,
  splitting: true,         // shared deps (date-fns, svelte runtime) extracted to chunks
  entryNames: '[name].[hash]',
  chunkNames: 'chunk-[name].[hash]',
  assetNames: '[name].[hash]',
  minify: true,
  sourcemap: 'linked',
  metafile: true,          // we read this to compute the manifest
  plugins: [sveltePlugin({ generate: 'client', dev: false }), cssPlugin()],
});
```

Each `.fymo/entries/<route>.client.js` is a tiny generated file:

```js
import { hydrate } from 'svelte';
import Component from '../../app/templates/<route>/index.svelte';
const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {};
hydrate(Component, { target: document.getElementById('svelte-app'), props });
```

Six lines, real ESM. The svelte plugin handles `.svelte` resolution; the css plugin extracts `<style>` to a sibling `.css` file.

### 4.4 Manifest

`dist/manifest.json` is the contract between the build output and the Python runtime:

```json
{
  "version": 1,
  "buildTime": "2026-04-28T12:34:56Z",
  "routes": {
    "todos": {
      "ssr": "ssr/todos.mjs",
      "client": "client/todos.A1B2C3.js",
      "css": "client/todos.A1B2C3.css",
      "preload": ["client/chunk-datefns.X9Y8.js", "client/chunk-svelte.D4E5.js"]
    },
    "home": { ... }
  }
}
```

Python reads it once at server startup and keeps it in memory. Each request looks up by route name in O(1).

### 4.5 `fymo dev` watcher

`fymo dev` runs the same pipeline with `context.watch()` (esbuild's incremental rebuild API). On every save, esbuild rebuilds only the affected entry — typically < 50 ms.

After rebuild:
1. esbuild's `onEnd` plugin writes a fresh `manifest.json` atomically (write to `manifest.json.tmp`, then `rename`).
2. The Python WSGI server detects the manifest mtime change on the next request and reloads it from disk.
3. **The sidecar is killed and respawned.** Node caches imported ES modules forever within a process, so the old `dist/ssr/<route>.mjs` would stay in memory. Dev mode kills + respawns the sidecar on every rebuild (~150 ms cold start, acceptable for dev). Prod never rebuilds, so this never happens after `fymo serve` start.
4. SSE channel notifies all open browser tabs to reload.

SSE reload: a 4-line WSGI `/dev/sse` endpoint that writes `data: reload\n\n` on rebuild. Client side, the dev-only entry adds a 5-line `EventSource` listener that calls `location.reload()`.

## 5. Node sidecar

### 5.1 Lifetime

`fymo serve` (and `fymo dev`) spawn one `node dist/sidecar.mjs` at startup. The Python process holds the sidecar's stdin/stdout. The sidecar process inherits stderr (so its logs surface in the server's terminal).

If the sidecar exits unexpectedly: respawn once, fail the in-flight request with a clear error, log the original stderr.

### 5.2 Wire protocol

Length-prefixed JSON on stdio. Each frame:

```
[4 bytes big-endian length][JSON payload of that length]
```

Payload shapes:

```ts
// Python → Node
{ id: number, type: 'render', route: string, props: object }
// Node → Python
{ id: number, ok: true, body: string, head: string }
// Node → Python (error)
{ id: number, ok: false, error: string, stack: string }
```

`id` lets multiple in-flight requests interleave (Python sends multiple, Node returns out-of-order). For initial implementation we serialize on the Python side (one request at a time) and revisit if profiling shows contention.

### 5.3 Sidecar code

`dist/sidecar.mjs` (build-emitted, ~30 lines):

```js
import { render } from 'svelte/server';

const cache = new Map();
const inbuf = [];
let want = null;

async function handle({ id, route, props }) {
  try {
    if (!cache.has(route)) cache.set(route, await import(new URL(`./ssr/${route}.mjs`, import.meta.url)));
    const { body, head } = render(cache.get(route).default, { props });
    write({ id, ok: true, body, head });
  } catch (err) {
    write({ id, ok: false, error: err.message, stack: err.stack });
  }
}

process.stdin.on('data', chunk => {
  inbuf.push(chunk);
  // consume length-prefixed frames; call handle() per frame
  // ... ~10 lines of framing
});
```

### 5.4 Python client

`fymo/core/sidecar.py`, ~80 lines:

```python
class Sidecar:
    def __init__(self, dist_dir: Path):
        self.proc = subprocess.Popen(
            ['node', str(dist_dir / 'sidecar.mjs')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            cwd=dist_dir,
        )
        self._lock = threading.Lock()
        self._next_id = itertools.count(1)

    def render(self, route: str, props: dict) -> dict:
        msg = {'id': next(self._next_id), 'type': 'render', 'route': route, 'props': props}
        payload = json.dumps(msg).encode('utf-8')
        with self._lock:
            self.proc.stdin.write(len(payload).to_bytes(4, 'big') + payload)
            self.proc.stdin.flush()
            length = int.from_bytes(self.proc.stdout.read(4), 'big')
            reply = json.loads(self.proc.stdout.read(length))
        if not reply['ok']:
            raise RenderingError(reply['error'], stack=reply['stack'])
        return reply  # has 'body' and 'head'
```

The `_lock` enforces single-flight; this is fine for dev and OK for prod with WSGI's per-request workers (each gunicorn worker has its own sidecar).

## 6. HTML output

The minimal-and-well-structured HTML the request initiated:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fymo Todo App</title>
  {head}                                                              <!-- from svelte/server's render() -->
  <link rel="stylesheet" href="/dist/client/todos.A1B2.css">
  <link rel="modulepreload" href="/dist/client/todos.A1B2.js">
  <link rel="modulepreload" href="/dist/client/chunk-datefns.X9Y8.js">
</head>
<body>
  <div id="svelte-app">{body}</div>
  <script type="application/json" id="svelte-props">{...}</script>
  <script type="module" src="/dist/client/todos.A1B2.js"></script>
</body>
</html>
```

Properties:
- All script and CSS bytes are in cacheable, hashed, externally-loaded files.
- Cross-route navigation reuses chunk bytes from disk cache.
- `modulepreload` hints let the browser fetch hydration JS in parallel with HTML.
- One `<script type="module">` tag, six lines of code in it on disk, no inline boilerplate, no fallback path, no `new Function`.

Target page weight for the todo example: ~5 KB HTML + cached deps.

## 7. Static asset serving

`fymo serve` adds one route: `GET /dist/<rest>` reads from the project's `dist/` directory and returns it with:
- `Content-Type` from extension.
- `Cache-Control: public, max-age=31536000, immutable` for hashed filenames (everything in `dist/client/`). Safe because URLs are content-hashed; bundle changes get new URLs.
- `Cache-Control: no-cache` for `manifest.json` only.
- Path traversal protection: reject any path containing `..` or null bytes; resolve and verify the result stays under `dist/`.

The framework-bundled svelte runtime is no longer served (it's now an esbuild dependency, not a runtime artifact). `_serve_svelte_runtime` and friends are deleted.

## 8. Errors

Build-time errors: esbuild aggregates them with file/line/column. `fymo build` exits non-zero, `fymo dev` keeps watching but serves a fixed dev-error page.

SSR errors: sidecar returns `{ok: false, error, stack}`. Python re-raises `RenderingError`. In dev: a structured error overlay with stack and source frame. In prod: 500 with the error logged, generic page returned.

Sidecar crash: respawn once, fail the current request with a clear `SidecarUnavailable` error.

Manifest missing or stale: 503 with "run `fymo build`" message in dev, 500 in prod.

## 9. Rollout

Each phase is a separate commit, gated by `FYMO_NEW_PIPELINE=1` env until phase 5 flips the default. The old code path stays in tree throughout phases 1–4 so nothing is broken between phases.

| Phase | Output | Acceptance test |
|-------|--------|-----------------|
| 1. Build pipeline (Node side) | `node fymo/cli/build.js` produces `dist/` for the todo example | `dist/manifest.json` exists; manual visual diff of compiled SSR vs. expected |
| 2. Sidecar (Python ↔ Node) | `fymo serve` (with flag) renders todos via sidecar; old path stays for unflagged requests | curl `/` returns the same SSR HTML with flag on/off, byte-identical body |
| 3. HTML emission | `_generate_html_page` reads manifest + emits minimal HTML | Page weight < 10 KB; Playwright hydration test passes |
| 4. `fymo dev` watcher | Edit a `.svelte`, browser auto-reloads in < 500 ms | Manual + scripted test |
| 5. Cleanup | Delete `runtime.py`, `bundler.py` regex paths, `_serve_svelte_runtime`, STPyV8 dep, `_compile_for_hydration`, etc. | `pytest`, plus Playwright run on todo + a new fixture using `node-fetch` (proves Node-only NPM works) |

## 10. Open questions / risks

1. **CSS plugin choice.** esbuild's built-in CSS handling for `.svelte` requires either a community plugin (`esbuild-svelte`) or a custom plugin. Picking the right one is the first build-pipeline decision. `esbuild-svelte` is maintained, used by Astro adapters, and supports preprocess. Default to it.
2. **Source maps in prod.** Linked sourcemaps are 200–400 % of the bundle size. Default to linked in dev, off in prod, configurable via `fymo.yml`.
3. **CSP.** Inline `<script type="application/json" id="svelte-props">` is a JSON literal, not executable, so it works under `script-src 'self'`. The single `<script type="module" src=…>` is also `'self'`. CSP is straightforward.
4. **Concurrency.** Single-flight sidecar is fine up to ~100 req/s on modern hardware. If higher throughput is needed, switch to a worker pool sharing one Node process via `worker_threads`. Not for v1.
5. **Hot-reload across sub-component changes.** Editing a non-route `.svelte` (e.g., `app/templates/todos/test.svelte`) needs to invalidate the parent route's bundle. esbuild's incremental graph handles this correctly; verify with the test fixture.
6. **Sidecar startup blocks first request.** Cold-start of `node + import('svelte/server')` is ~150 ms. Mitigation: warm the sidecar at server startup by sending a no-op `{type: 'ping'}` request before accepting traffic.

## 11. Out of scope (explicit non-features)

- File-based routing replacing `fymo.yml`.
- Layouts (`+layout.svelte`).
- TypeScript / SCSS preprocessing.
- API routes (`+server.py`).
- Streaming SSR / suspense.
- Component-level HMR with state preservation.
- Service-worker integration.
- Production deploy adapters.
