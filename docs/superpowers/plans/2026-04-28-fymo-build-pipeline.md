# Fymo build pipeline + Node sidecar SSR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Fymo's per-request V8/STPyV8 + regex-rewriting pipeline with a build-time esbuild pipeline plus a persistent Node sidecar for SSR. Reduce HTML response from ~95 KB to ~5 KB, enable cross-route shared chunks, and unlock "any npm library" support including those needing Node APIs.

**Architecture:** `fymo build` runs esbuild twice (server pass with `generate:'server'`, client pass with `generate:'client'` and `splitting:true`) to produce `dist/ssr/*.mjs`, `dist/client/*.<hash>.js`, `dist/client/*.<hash>.css`, plus `dist/manifest.json`. At request time, Python's WSGI app calls the controller (unchanged), then sends `{route, props}` to a long-lived Node sidecar over length-prefixed JSON on stdio. Sidecar imports the prebuilt SSR module once, calls `render(component, {props})` from `svelte/server`, returns `{body, head}`. Python emits a minimal HTML response with hashed `<link>` and `<script type="module" src=…>` to the client bundle.

**Tech Stack:** Python 3.12+ (WSGI), Node 18+, esbuild, esbuild-svelte, Svelte 5, pytest, Playwright (for hydration smoke test).

**Source spec:** `docs/superpowers/specs/2026-04-28-fymo-build-pipeline-design.md`.

---

## File structure

**Create:**
- `fymo/build/__init__.py` — exports `BuildPipeline`
- `fymo/build/pipeline.py` — Python orchestrator: discovers routes, generates entries, invokes Node build script
- `fymo/build/discovery.py` — finds route entries from `app/templates/`
- `fymo/build/manifest.py` — writes/reads `dist/manifest.json`
- `fymo/build/js/build.mjs` — Node-side: runs the two esbuild calls, emits manifest
- `fymo/build/js/sidecar.mjs` — Node-side SSR sidecar; copied verbatim into `dist/sidecar.mjs` at build time
- `fymo/build/js/sse_client.mjs` — tiny dev-only SSE listener appended to client entries in dev
- `fymo/core/sidecar.py` — Python ↔ Node IPC client (`Sidecar` class)
- `fymo/core/html.py` — minimal HTML builder reading the manifest
- `fymo/cli/commands/dev.py` — `fymo dev` command (watch mode)
- `tests/__init__.py`
- `tests/conftest.py` — shared pytest fixtures (project tmpdir + svelte/esbuild availability)
- `tests/build/test_discovery.py`
- `tests/build/test_pipeline.py`
- `tests/build/test_manifest.py`
- `tests/core/test_sidecar.py`
- `tests/core/test_html.py`
- `tests/integration/test_request_flow.py`
- `tests/integration/test_dev_watcher.py`

**Modify:**
- `fymo/cli/main.py` — add `dev` command, route `build` through new pipeline
- `fymo/cli/commands/build.py` — add new pipeline path
- `fymo/core/template_renderer.py` — when `FYMO_NEW_PIPELINE=1`, use sidecar+manifest path
- `fymo/core/server.py` — initialize `Sidecar` and manifest at startup; add `/dist/<...>` route
- `fymo/core/assets.py` — add `serve_dist_asset(path)`
- `package.json` — add `esbuild-svelte` dep
- `pyproject.toml` — add `pytest`/`playwright` dev extras (later: drop `stpyv8`)
- `.gitignore` — add `dist/`, `.fymo/cache/`

**Delete (Phase 5 only):**
- `fymo/core/runtime.py`
- `fymo/core/bundler.py`
- `fymo/core/component_resolver.py`
- `fymo/core/compiler.py`
- `fymo/bundler/` directory
- STPyV8 mentions in `pyproject.toml` / `requirements.txt`
- Old `_serve_svelte_runtime`, `_serve_svelte_runtime_path` from `assets.py`

---

## Phase 1 — Build pipeline (Node side + Python orchestrator)

Goal of this phase: `FYMO_NEW_PIPELINE=1 fymo build` produces a working `dist/` for the `examples/todo_app` fixture. No Python runtime path changes yet.

### Task 1: Bootstrap test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/build/__init__.py`
- Modify: `pyproject.toml` (add pytest config)

- [ ] **Step 1: Create empty test packages**

```bash
mkdir -p tests/build tests/core tests/integration
touch tests/__init__.py tests/build/__init__.py tests/core/__init__.py tests/integration/__init__.py
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures for fymo tests."""
import shutil
import subprocess
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_APP = REPO_ROOT / "examples" / "todo_app"


@pytest.fixture
def example_app(tmp_path: Path) -> Path:
    """Copy of examples/todo_app into an isolated tmp dir."""
    dest = tmp_path / "todo_app"
    shutil.copytree(EXAMPLE_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo"))
    # symlink node_modules from the original to save time
    (dest / "node_modules").symlink_to(EXAMPLE_APP / "node_modules")
    return dest


@pytest.fixture(scope="session")
def node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("node not installed")
        return False
```

- [ ] **Step 3: Add pytest config to `pyproject.toml`**

Add this section at the bottom of `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

- [ ] **Step 4: Verify pytest runs**

Run: `pytest tests/ -v`
Expected: `no tests ran` (exit 5 is fine — no tests yet).

- [ ] **Step 5: Commit**

```bash
git add tests/ pyproject.toml
git commit -m "test: bootstrap pytest infrastructure with example_app fixture"
```

### Task 2: Route discovery

**Files:**
- Create: `fymo/build/__init__.py`
- Create: `fymo/build/discovery.py`
- Test: `tests/build/test_discovery.py`

- [ ] **Step 1: Write the failing test**

`tests/build/test_discovery.py`:

```python
from pathlib import Path
from fymo.build.discovery import discover_routes, Route


def test_discover_finds_top_level_index_svelte(example_app: Path):
    routes = discover_routes(example_app / "app" / "templates")
    names = sorted(r.name for r in routes)
    assert names == ["home", "todos"]


def test_route_entry_path_is_absolute(example_app: Path):
    routes = discover_routes(example_app / "app" / "templates")
    for r in routes:
        assert r.entry_path.is_absolute()
        assert r.entry_path.name == "index.svelte"


def test_discover_ignores_non_index(tmp_path: Path):
    templates = tmp_path / "templates"
    (templates / "todos").mkdir(parents=True)
    (templates / "todos" / "index.svelte").write_text("<div></div>")
    (templates / "todos" / "test.svelte").write_text("<div></div>")  # not an entry
    routes = discover_routes(templates)
    assert [r.name for r in routes] == ["todos"]
```

- [ ] **Step 2: Run test — expect import failure**

Run: `pytest tests/build/test_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fymo.build'`.

- [ ] **Step 3: Implement `fymo/build/__init__.py`**

```python
"""Build pipeline for Fymo: produces dist/ from app/templates/."""
from fymo.build.discovery import discover_routes, Route

__all__ = ["discover_routes", "Route"]
```

- [ ] **Step 4: Implement `fymo/build/discovery.py`**

```python
"""Discover route entries from app/templates/."""
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class Route:
    """A route entry corresponds to one app/templates/<name>/index.svelte."""
    name: str
    entry_path: Path  # absolute path to index.svelte


def discover_routes(templates_dir: Path) -> List[Route]:
    """Return one Route per <templates_dir>/<name>/index.svelte."""
    if not templates_dir.is_dir():
        return []
    routes: List[Route] = []
    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir():
            continue
        entry = child / "index.svelte"
        if entry.is_file():
            routes.append(Route(name=child.name, entry_path=entry.resolve()))
    return routes
```

- [ ] **Step 5: Run test — expect pass**

Run: `pytest tests/build/test_discovery.py -v`
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add fymo/build/__init__.py fymo/build/discovery.py tests/build/test_discovery.py
git commit -m "feat(build): add route discovery from app/templates"
```

### Task 3: Manifest writer / reader

**Files:**
- Create: `fymo/build/manifest.py`
- Test: `tests/build/test_manifest.py`

- [ ] **Step 1: Write the failing test**

`tests/build/test_manifest.py`:

```python
import json
from pathlib import Path
from fymo.build.manifest import Manifest, RouteAssets


def test_write_and_read_roundtrip(tmp_path: Path):
    m = Manifest(routes={
        "todos": RouteAssets(
            ssr="ssr/todos.mjs",
            client="client/todos.A1B2.js",
            css="client/todos.A1B2.css",
            preload=["client/chunk-datefns.X9Y8.js"],
        )
    })
    out = tmp_path / "manifest.json"
    m.write(out)

    loaded = Manifest.read(out)
    assert loaded == m
    assert loaded.routes["todos"].css == "client/todos.A1B2.css"


def test_atomic_write_via_rename(tmp_path: Path):
    out = tmp_path / "manifest.json"
    Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.X.js", css=None, preload=[])}).write(out)
    assert out.exists()
    assert not (tmp_path / "manifest.json.tmp").exists()
    data = json.loads(out.read_text())
    assert data["version"] == 1
    assert data["routes"]["home"]["ssr"] == "ssr/home.mjs"


def test_read_missing_returns_none(tmp_path: Path):
    assert Manifest.read(tmp_path / "missing.json") is None


def test_read_rejects_unknown_version(tmp_path: Path):
    out = tmp_path / "manifest.json"
    out.write_text(json.dumps({"version": 99, "routes": {}}))
    import pytest
    with pytest.raises(ValueError, match="version"):
        Manifest.read(out)
```

- [ ] **Step 2: Run test — expect import failure**

Run: `pytest tests/build/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `fymo/build/manifest.py`**

```python
"""dist/manifest.json read/write contract between build and runtime."""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


MANIFEST_VERSION = 1


@dataclass(frozen=True)
class RouteAssets:
    ssr: str            # path relative to dist/, e.g. "ssr/todos.mjs"
    client: str         # path relative to dist/, e.g. "client/todos.A1B2.js"
    css: Optional[str]  # path relative to dist/, or None if no styles
    preload: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    routes: Dict[str, RouteAssets]
    build_time: str = ""

    def write(self, path: Path) -> None:
        data = {
            "version": MANIFEST_VERSION,
            "buildTime": self.build_time,
            "routes": {name: asdict(r) for name, r in self.routes.items()},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)

    @classmethod
    def read(cls, path: Path) -> Optional["Manifest"]:
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        if data.get("version") != MANIFEST_VERSION:
            raise ValueError(
                f"manifest.json version {data.get('version')} unsupported "
                f"(expected {MANIFEST_VERSION}); rebuild with `fymo build`"
            )
        routes = {
            name: RouteAssets(
                ssr=r["ssr"],
                client=r["client"],
                css=r.get("css"),
                preload=list(r.get("preload", [])),
            )
            for name, r in data.get("routes", {}).items()
        }
        return cls(routes=routes, build_time=data.get("buildTime", ""))
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/build/test_manifest.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/build/manifest.py tests/build/test_manifest.py
git commit -m "feat(build): add manifest read/write with atomic rename"
```

### Task 4: Add esbuild-svelte dependency

**Files:**
- Modify: `package.json`
- Modify: `examples/todo_app/package.json`

- [ ] **Step 1: Add dep to root `package.json`**

In `package.json`, under `"devDependencies"`, add:

```json
"esbuild-svelte": "^0.9.0",
"esbuild": "^0.25.9"
```

(Keep `svelte` at `^5.38.6`.)

- [ ] **Step 2: Add same to `examples/todo_app/package.json`**

In `examples/todo_app/package.json`, under `"devDependencies"`, add:

```json
"esbuild-svelte": "^0.9.0"
```

- [ ] **Step 3: Install**

Run from repo root:
```bash
npm install
cd examples/todo_app && npm install && cd -
```

Expected: both lockfiles updated, exit 0, no peer-dep warnings about svelte 5.

- [ ] **Step 4: Verify the package resolves Svelte 5**

Run:
```bash
cd examples/todo_app && node -e "import('esbuild-svelte').then(m => console.log(typeof m.default))"
```

Expected output: `function`.

- [ ] **Step 5: Commit**

```bash
git add package.json package-lock.json examples/todo_app/package.json examples/todo_app/package-lock.json
git commit -m "deps: add esbuild-svelte and pin esbuild for build pipeline"
```

### Task 5: Generate client entry stubs

**Files:**
- Create: `fymo/build/entry_generator.py`
- Test: `tests/build/test_entry_generator.py`

The client entry per route is a tiny JS file that calls `hydrate(Component, {target, props})`.

- [ ] **Step 1: Write the failing test**

`tests/build/test_entry_generator.py`:

```python
from pathlib import Path
from fymo.build.discovery import Route
from fymo.build.entry_generator import write_client_entries


def test_writes_one_entry_per_route(tmp_path: Path):
    route1 = Route(name="todos", entry_path=tmp_path / "templates/todos/index.svelte")
    route2 = Route(name="home", entry_path=tmp_path / "templates/home/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"

    paths = write_client_entries([route1, route2], out_dir, project_root=tmp_path)

    assert (out_dir / "todos.client.js").exists()
    assert (out_dir / "home.client.js").exists()
    assert paths["todos"] == out_dir / "todos.client.js"


def test_entry_imports_hydrate_and_component(tmp_path: Path):
    route = Route(name="todos", entry_path=tmp_path / "templates/todos/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"
    write_client_entries([route], out_dir, project_root=tmp_path)

    text = (out_dir / "todos.client.js").read_text()
    assert "import { hydrate } from 'svelte'" in text
    # relative import path from .fymo/entries/ back to templates/todos/index.svelte
    assert "../../templates/todos/index.svelte" in text
    assert "hydrate(Component" in text
    assert "svelte-app" in text
    assert "svelte-props" in text
```

- [ ] **Step 2: Run test — expect import failure**

Run: `pytest tests/build/test_entry_generator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/build/entry_generator.py`**

```python
"""Generate per-route client entry stubs for esbuild."""
import os
from pathlib import Path
from typing import Dict, Iterable
from fymo.build.discovery import Route


CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate }} from 'svelte';
import Component from '{component_import}';

const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {{}};
const target = document.getElementById('svelte-app');

hydrate(Component, {{ target, props }});
"""


def write_client_entries(routes: Iterable[Route], out_dir: Path, project_root: Path) -> Dict[str, Path]:
    """Write a client entry per route, returning {route_name: entry_path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for route in routes:
        rel = os.path.relpath(route.entry_path, out_dir)
        # esbuild needs forward slashes in import paths
        component_import = rel.replace(os.sep, "/")
        if not component_import.startswith("."):
            component_import = "./" + component_import
        entry_path = out_dir / f"{route.name}.client.js"
        entry_path.write_text(CLIENT_ENTRY_TEMPLATE.format(component_import=component_import))
        written[route.name] = entry_path
    return written
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/build/test_entry_generator.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/build/entry_generator.py tests/build/test_entry_generator.py
git commit -m "feat(build): generate per-route client hydration entries"
```

### Task 6: Node build script — server pass

**Files:**
- Create: `fymo/build/js/build.mjs`
- Create: `fymo/build/js/sidecar.mjs` (template)
- Test: manually invoked via Python in Task 8

- [ ] **Step 1: Write `fymo/build/js/sidecar.mjs`** (will be copied verbatim into `dist/`)

```javascript
#!/usr/bin/env node
import { render } from 'svelte/server';

const cache = new Map();
const stdout = process.stdout;
const stdin = process.stdin;

let buf = Buffer.alloc(0);
let want = null; // bytes of next frame body, or null when reading length

stdin.on('data', chunk => {
    buf = Buffer.concat([buf, chunk]);
    void drain();
});

stdin.on('end', () => process.exit(0));

function writeFrame(obj) {
    const body = Buffer.from(JSON.stringify(obj), 'utf8');
    const len = Buffer.alloc(4);
    len.writeUInt32BE(body.length, 0);
    stdout.write(Buffer.concat([len, body]));
}

async function loadModule(route) {
    if (!cache.has(route)) {
        const url = new URL(`./ssr/${route}.mjs`, import.meta.url);
        cache.set(route, await import(url.href));
    }
    return cache.get(route);
}

async function handle(msg) {
    const { id, type } = msg;
    try {
        if (type === 'ping') {
            writeFrame({ id, ok: true });
            return;
        }
        if (type === 'render') {
            const mod = await loadModule(msg.route);
            const out = render(mod.default, { props: msg.props || {} });
            writeFrame({ id, ok: true, body: out.body, head: out.head });
            return;
        }
        writeFrame({ id, ok: false, error: `unknown type: ${type}`, stack: '' });
    } catch (err) {
        writeFrame({
            id,
            ok: false,
            error: err && err.message ? err.message : String(err),
            stack: err && err.stack ? err.stack : '',
        });
    }
}

async function drain() {
    while (true) {
        if (want === null) {
            if (buf.length < 4) return;
            want = buf.readUInt32BE(0);
            buf = buf.subarray(4);
        }
        if (buf.length < want) return;
        const body = buf.subarray(0, want);
        buf = buf.subarray(want);
        want = null;
        let msg;
        try {
            msg = JSON.parse(body.toString('utf8'));
        } catch (err) {
            writeFrame({ id: 0, ok: false, error: 'invalid JSON frame', stack: err.stack });
            continue;
        }
        await handle(msg);
    }
}
```

- [ ] **Step 2: Write `fymo/build/js/build.mjs`** (server pass only for now)

```javascript
#!/usr/bin/env node
/**
 * Fymo build — invoked by Python orchestrator.
 *
 * Reads a JSON config from argv[2]:
 *   { projectRoot, distDir, routes: [{name, entryPath}], clientEntries: {name: path}, dev }
 *
 * Writes:
 *   <distDir>/ssr/<route>.mjs              (server pass)
 *   <distDir>/sidecar.mjs                  (copied)
 * Prints:
 *   { ok: true, server: { ... metafile ... } } on stdout
 */
import { build } from 'esbuild';
import sveltePlugin from 'esbuild-svelte';
import { sveltePreprocess } from 'svelte-preprocess';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(process.argv[2]);

async function buildServer() {
    const entryPoints = Object.fromEntries(
        config.routes.map(r => [r.name, r.entryPath])
    );
    return await build({
        entryPoints,
        outdir: path.join(config.distDir, 'ssr'),
        outExtension: { '.js': '.mjs' },
        format: 'esm',
        platform: 'node',
        bundle: true,
        splitting: false,
        minify: !config.dev,
        sourcemap: config.dev ? 'linked' : false,
        metafile: true,
        plugins: [sveltePlugin({
            compilerOptions: { generate: 'server', dev: false },
        })],
        logLevel: 'silent',
    });
}

async function copySidecar() {
    const src = path.join(__dirname, 'sidecar.mjs');
    const dst = path.join(config.distDir, 'sidecar.mjs');
    await fs.mkdir(path.dirname(dst), { recursive: true });
    await fs.copyFile(src, dst);
}

try {
    await fs.mkdir(config.distDir, { recursive: true });
    const server = await buildServer();
    await copySidecar();
    process.stdout.write(JSON.stringify({ ok: true, server: server.metafile }));
} catch (err) {
    process.stdout.write(JSON.stringify({
        ok: false,
        error: err.message || String(err),
        stack: err.stack || '',
    }));
    process.exit(1);
}
```

- [ ] **Step 3: Add `svelte-preprocess` to `examples/todo_app/package.json` devDependencies**

```json
"svelte-preprocess": "^6.0.0"
```

(svelte-preprocess is optional — the script imports it but doesn't enable preprocessing yet. Keeps the door open.)

Actually, simpler: drop the preprocess import for now. Edit `build.mjs` step 2 above and remove the line `import { sveltePreprocess } from 'svelte-preprocess';`. Skip this step.

- [ ] **Step 4: Manually verify the script runs from the example app**

Run:
```bash
cd /Users/bishwasbhandari/Projects/fymo/examples/todo_app
node ../../fymo/build/js/build.mjs '{"projectRoot":"'"$PWD"'","distDir":"'"$PWD"'/dist","routes":[{"name":"todos","entryPath":"'"$PWD"'/app/templates/todos/index.svelte"}],"clientEntries":{},"dev":false}'
```

Expected: stdout contains `{"ok":true,...}`. `dist/ssr/todos.mjs` and `dist/sidecar.mjs` exist.

- [ ] **Step 5: Sanity-check the SSR module exports a function**

```bash
cd /Users/bishwasbhandari/Projects/fymo/examples/todo_app
node -e "import('./dist/ssr/todos.mjs').then(m => console.log(typeof m.default))"
```

Expected: `function`.

- [ ] **Step 6: Commit**

```bash
git add fymo/build/js/build.mjs fymo/build/js/sidecar.mjs
git commit -m "feat(build): add Node build script (server pass) and sidecar template"
```

### Task 7: Node build script — client pass with code splitting

**Files:**
- Modify: `fymo/build/js/build.mjs`

- [ ] **Step 1: Add `buildClient` function**

In `fymo/build/js/build.mjs`, add this function alongside `buildServer`:

```javascript
async function buildClient() {
    const entryPoints = Object.fromEntries(
        Object.entries(config.clientEntries).map(([name, p]) => [name, p])
    );
    return await build({
        entryPoints,
        outdir: path.join(config.distDir, 'client'),
        format: 'esm',
        platform: 'browser',
        bundle: true,
        splitting: true,
        entryNames: '[name].[hash]',
        chunkNames: 'chunk-[name].[hash]',
        assetNames: '[name].[hash]',
        minify: !config.dev,
        sourcemap: config.dev ? 'linked' : false,
        metafile: true,
        plugins: [sveltePlugin({
            compilerOptions: { generate: 'client', dev: false },
        })],
        logLevel: 'silent',
    });
}
```

- [ ] **Step 2: Wire `buildClient` into the main flow**

Replace the body of the top-level `try` block (between `await fs.mkdir(...)` and `process.stdout.write({ok:true, ...})`) with:

```javascript
    await fs.mkdir(config.distDir, { recursive: true });
    const server = await buildServer();
    const client = await buildClient();
    await copySidecar();
    process.stdout.write(JSON.stringify({ ok: true, server: server.metafile, client: client.metafile }));
```

- [ ] **Step 3: Manually verify with the example app**

```bash
cd /Users/bishwasbhandari/Projects/fymo/examples/todo_app
mkdir -p .fymo/entries
cat > .fymo/entries/todos.client.js <<'EOF'
import { hydrate } from 'svelte';
import Component from '../../app/templates/todos/index.svelte';
const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {};
const target = document.getElementById('svelte-app');
hydrate(Component, { target, props });
EOF

CONFIG=$(cat <<EOF
{"projectRoot":"$PWD","distDir":"$PWD/dist","routes":[{"name":"todos","entryPath":"$PWD/app/templates/todos/index.svelte"}],"clientEntries":{"todos":"$PWD/.fymo/entries/todos.client.js"},"dev":false}
EOF
)
node ../../fymo/build/js/build.mjs "$CONFIG"
```

Expected:
- stdout: `{"ok":true,...}`
- `ls dist/client/` shows `todos.<HASH>.js` and `todos.<HASH>.css` (CSS may be missing on first run if Svelte styles not extracted; that's fine for now).

- [ ] **Step 4: Verify the client bundle contains hydrate**

```bash
cd /Users/bishwasbhandari/Projects/fymo/examples/todo_app
grep -c "hydrate" dist/client/todos.*.js
```

Expected: at least 1.

- [ ] **Step 5: Commit**

```bash
git add fymo/build/js/build.mjs
git commit -m "feat(build): add client pass with code splitting"
```

### Task 8: Python build pipeline orchestrator

**Files:**
- Create: `fymo/build/pipeline.py`
- Test: `tests/build/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/build/test_pipeline.py`:

```python
import json
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline, BuildError


@pytest.mark.usefixtures("node_available")
def test_build_produces_dist_for_example_app(example_app: Path):
    pipeline = BuildPipeline(project_root=example_app)
    result = pipeline.build(dev=False)

    assert result.ok
    assert (example_app / "dist" / "manifest.json").is_file()
    assert (example_app / "dist" / "ssr" / "todos.mjs").is_file()
    assert (example_app / "dist" / "sidecar.mjs").is_file()

    # at least one hashed client bundle
    client_files = list((example_app / "dist" / "client").glob("todos.*.js"))
    assert len(client_files) == 1


@pytest.mark.usefixtures("node_available")
def test_manifest_lists_each_route(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    assert "todos" in manifest["routes"]
    todos = manifest["routes"]["todos"]
    assert todos["ssr"] == "ssr/todos.mjs"
    assert todos["client"].startswith("client/todos.")
    assert todos["client"].endswith(".js")


def test_build_fails_loudly_on_missing_node(example_app: Path, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(BuildError, match="node"):
        BuildPipeline(project_root=example_app).build(dev=False)
```

- [ ] **Step 2: Run test — expect import failure**

Run: `pytest tests/build/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `fymo/build/pipeline.py`**

```python
"""Python orchestrator for the Node-side build script."""
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fymo.build.discovery import discover_routes
from fymo.build.entry_generator import write_client_entries
from fymo.build.manifest import Manifest, RouteAssets


class BuildError(RuntimeError):
    """Raised when the build pipeline fails."""


@dataclass
class BuildResult:
    ok: bool
    manifest_path: Path


class BuildPipeline:
    """Orchestrates: discover -> generate entries -> invoke esbuild -> write manifest."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.dist_dir = project_root / "dist"
        self.cache_dir = project_root / ".fymo" / "entries"
        self.build_script = Path(__file__).resolve().parent / "js" / "build.mjs"

    def build(self, dev: bool = False) -> BuildResult:
        if shutil.which("node") is None:
            raise BuildError("node executable not found on PATH")

        templates_dir = self.project_root / "app" / "templates"
        routes = discover_routes(templates_dir)
        if not routes:
            raise BuildError(f"no routes found under {templates_dir}")

        client_entry_paths = write_client_entries(routes, self.cache_dir, self.project_root)

        config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": [
                {"name": r.name, "entryPath": str(r.entry_path)} for r in routes
            ],
            "clientEntries": {
                name: str(path) for name, path in client_entry_paths.items()
            },
            "dev": dev,
        }

        proc = subprocess.run(
            ["node", str(self.build_script), json.dumps(config)],
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0 or not proc.stdout:
            raise BuildError(
                f"esbuild failed (exit {proc.returncode})\n"
                f"stdout: {proc.stdout}\n"
                f"stderr: {proc.stderr}"
            )

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BuildError(f"build script produced invalid JSON: {e}\nstdout: {proc.stdout[:500]}")

        if not result.get("ok"):
            raise BuildError(f"build failed: {result.get('error')}\n{result.get('stack', '')}")

        manifest = self._build_manifest(routes, result)
        manifest.write(self.dist_dir / "manifest.json")
        return BuildResult(ok=True, manifest_path=self.dist_dir / "manifest.json")

    def _build_manifest(self, routes, esbuild_result) -> Manifest:
        # Resolve hashed client filenames from the metafile.
        client_meta = esbuild_result.get("client", {}).get("outputs", {})
        # esbuild metafile keys are paths relative to cwd; normalize to dist/...
        client_by_route = {}
        css_by_route = {}
        for out_path, info in client_meta.items():
            entry_point = info.get("entryPoint")
            if entry_point is None:
                continue
            rel_to_dist = Path(out_path).resolve().relative_to(self.dist_dir.resolve())
            for r in routes:
                if Path(entry_point).name == f"{r.name}.client.js":
                    if str(rel_to_dist).endswith(".js"):
                        client_by_route[r.name] = str(rel_to_dist).replace("\\", "/")
                    elif str(rel_to_dist).endswith(".css"):
                        css_by_route[r.name] = str(rel_to_dist).replace("\\", "/")

        # Preload chunks: any output whose path starts with client/chunk-
        chunks = [
            str(Path(p).resolve().relative_to(self.dist_dir.resolve())).replace("\\", "/")
            for p in client_meta
            if Path(p).name.startswith("chunk-") and p.endswith(".js")
        ]

        route_assets = {}
        for r in routes:
            if r.name not in client_by_route:
                raise BuildError(f"esbuild produced no client output for route '{r.name}'")
            route_assets[r.name] = RouteAssets(
                ssr=f"ssr/{r.name}.mjs",
                client=client_by_route[r.name],
                css=css_by_route.get(r.name),
                preload=chunks,
            )

        return Manifest(
            routes=route_assets,
            build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
```

- [ ] **Step 4: Update `fymo/build/__init__.py` to export `BuildPipeline`**

```python
"""Build pipeline for Fymo: produces dist/ from app/templates/."""
from fymo.build.discovery import discover_routes, Route
from fymo.build.manifest import Manifest, RouteAssets
from fymo.build.pipeline import BuildPipeline, BuildError, BuildResult

__all__ = [
    "discover_routes", "Route",
    "Manifest", "RouteAssets",
    "BuildPipeline", "BuildError", "BuildResult",
]
```

- [ ] **Step 5: Run test — expect pass**

Run: `pytest tests/build/test_pipeline.py -v`
Expected: 3 PASSED (the third is `test_build_fails_loudly_on_missing_node`).

- [ ] **Step 6: Commit**

```bash
git add fymo/build/pipeline.py fymo/build/__init__.py tests/build/test_pipeline.py
git commit -m "feat(build): add Python orchestrator that invokes esbuild and writes manifest"
```

### Task 9: Wire `fymo build` to use new pipeline behind flag

**Files:**
- Modify: `fymo/cli/commands/build.py`
- Modify: `fymo/cli/main.py` (no changes if `build` already wired)
- Test: `tests/integration/test_cli_build.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_cli_build.py`:

```python
import os
import subprocess
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_fymo_build_with_flag_uses_new_pipeline(example_app: Path):
    env = {**os.environ, "FYMO_NEW_PIPELINE": "1"}
    proc = subprocess.run(
        ["fymo", "build"],
        cwd=example_app,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (example_app / "dist" / "manifest.json").is_file()
    assert (example_app / "dist" / "sidecar.mjs").is_file()


def test_fymo_build_without_flag_keeps_old_path(example_app: Path):
    proc = subprocess.run(
        ["fymo", "build"],
        cwd=example_app,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    # Old path doesn't produce manifest.json
    assert not (example_app / "dist" / "manifest.json").exists()
```

- [ ] **Step 2: Run test — expect failure (flag not wired)**

Run: `pytest tests/integration/test_cli_build.py -v`
Expected: FAIL.

- [ ] **Step 3: Modify `fymo/cli/commands/build.py`**

Add at the top of the file:
```python
import os
from fymo.build.pipeline import BuildPipeline, BuildError
```

Replace the body of `build_project` to branch on the flag:

```python
def build_project(output: str = 'dist', minify: bool = False):
    """Build the project for production."""
    project_root = Path.cwd()

    if os.environ.get("FYMO_NEW_PIPELINE") == "1":
        Color.print_info("Building with new pipeline (esbuild + Node sidecar)")
        try:
            BuildPipeline(project_root=project_root).build(dev=False)
        except BuildError as e:
            Color.print_error(str(e))
            raise SystemExit(1)
        Color.print_success(f"Built to {project_root / 'dist'}/")
        return

    # Legacy path
    Color.print_info(f"Building project to {output}/")
    ensure_svelte_runtime(project_root)
    Color.print_success("Project built successfully!")
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/integration/test_cli_build.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/cli/commands/build.py tests/integration/test_cli_build.py
git commit -m "feat(cli): route fymo build through new pipeline when FYMO_NEW_PIPELINE=1"
```

---

## Phase 2 — Sidecar (Python ↔ Node) IPC

Goal of this phase: At request time, Python can call `sidecar.render(route, props)` and get back `{body, head}`. No HTML emission changes yet.

### Task 10: Sidecar Python client

**Files:**
- Create: `fymo/core/sidecar.py`
- Test: `tests/core/test_sidecar.py`

- [ ] **Step 1: Write the failing test**

`tests/core/test_sidecar.py`:

```python
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline
from fymo.core.sidecar import Sidecar, SidecarError


@pytest.mark.usefixtures("node_available")
def test_render_returns_body_and_head(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        result = sidecar.render(route="todos", props={"todos": [], "user": {"name": "Test"}, "stats": {}})
        assert "body" in result
        assert "head" in result
        assert isinstance(result["body"], str)
        assert "todo-app" in result["body"]
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_render_propagates_errors(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        with pytest.raises(SidecarError):
            sidecar.render(route="nonexistent_route", props={})
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_ping_warms_module_cache(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        assert sidecar.ping() is True
    finally:
        sidecar.stop()
```

- [ ] **Step 2: Run test — expect import failure**

Run: `pytest tests/core/test_sidecar.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `fymo/core/sidecar.py`**

```python
"""Persistent Node sidecar IPC client.

Python ↔ Node protocol: length-prefixed JSON frames on stdio.
Frame format: [4-byte big-endian length][UTF-8 JSON payload of that length]
"""
import itertools
import json
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class SidecarError(RuntimeError):
    """Raised when the sidecar reports an error or is unavailable."""

    def __init__(self, message: str, stack: str = ""):
        super().__init__(message)
        self.stack = stack


class Sidecar:
    """Long-lived Node SSR sidecar managed from Python."""

    def __init__(self, dist_dir: Path):
        self.dist_dir = Path(dist_dir).resolve()
        self.script = self.dist_dir / "sidecar.mjs"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = itertools.count(1)

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if not self.script.is_file():
            raise SidecarError(f"sidecar script not found at {self.script}; run `fymo build` first")
        self._proc = subprocess.Popen(
            ["node", str(self.script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # inherit so logs surface
            cwd=str(self.dist_dir),
        )

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None

    def ping(self) -> bool:
        reply = self._send({"type": "ping"})
        return reply.get("ok") is True

    def render(self, route: str, props: Dict[str, Any]) -> Dict[str, str]:
        reply = self._send({"type": "render", "route": route, "props": props})
        return {"body": reply["body"], "head": reply["head"]}

    def _send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        if self._proc is None or self._proc.poll() is not None:
            raise SidecarError("sidecar not running; call start() first")

        msg_id = next(self._next_id)
        msg["id"] = msg_id
        body = json.dumps(msg).encode("utf-8")
        frame = struct.pack(">I", len(body)) + body

        with self._lock:
            try:
                self._proc.stdin.write(frame)
                self._proc.stdin.flush()
                length_bytes = self._read_exact(4)
                (length,) = struct.unpack(">I", length_bytes)
                payload = self._read_exact(length)
            except (BrokenPipeError, OSError) as e:
                raise SidecarError(f"sidecar IPC failure: {e}")

        reply = json.loads(payload.decode("utf-8"))
        if not reply.get("ok"):
            raise SidecarError(reply.get("error", "unknown sidecar error"), reply.get("stack", ""))
        return reply

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._proc.stdout.read(n - len(buf))
            if not chunk:
                raise SidecarError("sidecar stdout closed")
            buf += chunk
        return buf
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/core/test_sidecar.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/sidecar.py tests/core/test_sidecar.py
git commit -m "feat(core): add Node sidecar IPC client with length-prefixed JSON framing"
```

### Task 11: Manifest cache (Python)

**Files:**
- Create: `fymo/core/manifest_cache.py`
- Test: `tests/core/test_manifest_cache.py`

- [ ] **Step 1: Write the failing test**

`tests/core/test_manifest_cache.py`:

```python
import json
import time
from pathlib import Path
from fymo.build.manifest import Manifest, RouteAssets
from fymo.core.manifest_cache import ManifestCache, ManifestUnavailable
import pytest


def test_loads_manifest_on_first_access(tmp_path: Path):
    Manifest(routes={"todos": RouteAssets(ssr="ssr/todos.mjs", client="client/todos.AB.js", css=None, preload=[])}).write(tmp_path / "manifest.json")
    cache = ManifestCache(tmp_path)
    assert cache.get().routes["todos"].ssr == "ssr/todos.mjs"


def test_reloads_when_file_mtime_changes(tmp_path: Path):
    p = tmp_path / "manifest.json"
    Manifest(routes={"todos": RouteAssets(ssr="ssr/todos.mjs", client="client/todos.A.js", css=None, preload=[])}).write(p)
    cache = ManifestCache(tmp_path)
    cache.get()  # prime

    time.sleep(0.01)  # mtime resolution
    Manifest(routes={"todos": RouteAssets(ssr="ssr/todos.mjs", client="client/todos.B.js", css=None, preload=[])}).write(p)

    assert cache.get().routes["todos"].client == "client/todos.B.js"


def test_raises_if_manifest_missing(tmp_path: Path):
    cache = ManifestCache(tmp_path)
    with pytest.raises(ManifestUnavailable):
        cache.get()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/core/test_manifest_cache.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/core/manifest_cache.py`**

```python
"""Per-process manifest cache that auto-reloads on file change (dev hot-reload)."""
from pathlib import Path
from threading import Lock
from typing import Optional
from fymo.build.manifest import Manifest


class ManifestUnavailable(RuntimeError):
    """Raised when manifest.json doesn't exist (build hasn't run)."""


class ManifestCache:
    def __init__(self, dist_dir: Path):
        self.dist_dir = Path(dist_dir)
        self.path = self.dist_dir / "manifest.json"
        self._cached: Optional[Manifest] = None
        self._cached_mtime: Optional[float] = None
        self._lock = Lock()

    def get(self) -> Manifest:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                raise ManifestUnavailable(
                    f"{self.path} not found; run `fymo build` first"
                )

            if self._cached is None or mtime != self._cached_mtime:
                self._cached = Manifest.read(self.path)
                self._cached_mtime = mtime
                if self._cached is None:
                    raise ManifestUnavailable(f"failed to read {self.path}")
            return self._cached

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
            self._cached_mtime = None
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/core/test_manifest_cache.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/manifest_cache.py tests/core/test_manifest_cache.py
git commit -m "feat(core): add manifest cache with mtime-based auto-reload"
```

### Task 12: Wire sidecar+manifest into TemplateRenderer behind flag

**Files:**
- Modify: `fymo/core/template_renderer.py`
- Modify: `fymo/core/server.py`
- Test: `tests/integration/test_request_flow.py`

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_request_flow.py`:

```python
import os
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_request_renders_via_sidecar_when_flag_set(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")
    monkeypatch.chdir(example_app)

    from fymo import create_app
    app = create_app(example_app)

    # Use the WSGI app directly with a fake environ
    responses = []
    def start_response(status, headers):
        responses.append((status, headers))

    body = b"".join(app({
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": __import__("io").BytesIO(),
        "wsgi.errors": __import__("sys").stderr,
        "wsgi.url_scheme": "http",
    }, start_response))

    assert responses[0][0].startswith("200")
    text = body.decode("utf-8")
    assert "todo-app" in text
    assert "<div id=\"svelte-app\">" in text

    # Cleanup: stop sidecar
    if hasattr(app, 'sidecar') and app.sidecar:
        app.sidecar.stop()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/integration/test_request_flow.py -v`
Expected: FAIL — sidecar not wired.

- [ ] **Step 3: Modify `fymo/core/server.py` to initialize sidecar+manifest cache**

In `FymoApp.__init__`, after the existing initialization, add:

```python
        # New pipeline: sidecar + manifest cache
        self.sidecar = None
        self.manifest_cache = None
        if os.environ.get("FYMO_NEW_PIPELINE") == "1":
            from fymo.core.sidecar import Sidecar
            from fymo.core.manifest_cache import ManifestCache
            dist_dir = project_root / "dist"
            if (dist_dir / "sidecar.mjs").is_file():
                self.sidecar = Sidecar(dist_dir=dist_dir)
                self.sidecar.start()
                self.sidecar.ping()  # warm
                self.manifest_cache = ManifestCache(dist_dir=dist_dir)
                # Pass to template renderer
                self.template_renderer.sidecar = self.sidecar
                self.template_renderer.manifest_cache = self.manifest_cache
```

Add `import os` at the top of the file if not already imported.

Also add a `__del__` method:

```python
    def __del__(self):
        if getattr(self, 'sidecar', None) is not None:
            try:
                self.sidecar.stop()
            except Exception:
                pass
```

- [ ] **Step 4: Modify `fymo/core/template_renderer.py` to use sidecar when present**

In `TemplateRenderer.__init__`, add at the end:

```python
        self.sidecar = None
        self.manifest_cache = None
```

In `render_template`, add this branch at the very top of the `try:` block (before the existing logic):

```python
            if self.sidecar is not None and self.manifest_cache is not None:
                return self._render_via_sidecar(route_path)
```

Add the new method:

```python
    def _render_via_sidecar(self, route_path: str) -> Tuple[str, str]:
        """New pipeline: render via Node sidecar with prebuilt SSR module."""
        from fymo.core.sidecar import SidecarError
        from fymo.core.manifest_cache import ManifestUnavailable

        route_info = self.router.match(route_path)
        if not route_info:
            return self._render_404(), "404 NOT FOUND"

        # Map "todos.index" -> "todos" for manifest lookup
        route_name = route_info["controller"]
        controller_module = f"app.controllers.{route_info['controller']}"
        _, props, doc_meta = self._load_controller_data(controller_module)

        try:
            manifest = self.manifest_cache.get()
        except ManifestUnavailable as e:
            return f"<div>Build error: {e}</div>", "500 INTERNAL SERVER ERROR"

        if route_name not in manifest.routes:
            return f"<div>Route '{route_name}' not in manifest. Run `fymo build`.</div>", "500 INTERNAL SERVER ERROR"

        try:
            ssr = self.sidecar.render(route_name, props)
        except SidecarError as e:
            return f"<div>SSR Error: {e}</div>", "500 INTERNAL SERVER ERROR"

        # Reuse existing _generate_html_page for now (Phase 3 replaces this)
        full_html = self._generate_html_page(ssr["body"], props, "/* sidecar mode: hydration TBD in phase 3 */", doc_meta)
        return full_html, "200 OK"
```

(Leave the legacy code path intact below this branch.)

- [ ] **Step 5: Run test — expect pass**

Run: `pytest tests/integration/test_request_flow.py -v`
Expected: 1 PASSED.

- [ ] **Step 6: Commit**

```bash
git add fymo/core/server.py fymo/core/template_renderer.py tests/integration/test_request_flow.py
git commit -m "feat(core): wire sidecar+manifest into TemplateRenderer behind FYMO_NEW_PIPELINE"
```

---

## Phase 3 — Minimal HTML emission

Goal of this phase: HTML response is < 10 KB, references hashed JS/CSS via `<link>` and `<script type="module" src=…>`, and hydration works in a real browser.

### Task 13: Minimal HTML builder

**Files:**
- Create: `fymo/core/html.py`
- Test: `tests/core/test_html.py`

- [ ] **Step 1: Write the failing test**

`tests/core/test_html.py`:

```python
from fymo.build.manifest import RouteAssets
from fymo.core.html import build_html


def test_minimal_html_structure():
    assets = RouteAssets(
        ssr="ssr/todos.mjs",
        client="client/todos.A1B2.js",
        css="client/todos.A1B2.css",
        preload=["client/chunk-datefns.X9Y8.js"],
    )
    html = build_html(
        body="<div class='todo-app'>hi</div>",
        head_extra="",
        props={"todos": []},
        assets=assets,
        title="Todos",
        asset_prefix="/dist",
    )
    assert "<!DOCTYPE html>" in html
    assert "<title>Todos</title>" in html
    assert '<link rel="stylesheet" href="/dist/client/todos.A1B2.css">' in html
    assert '<link rel="modulepreload" href="/dist/client/todos.A1B2.js">' in html
    assert '<link rel="modulepreload" href="/dist/client/chunk-datefns.X9Y8.js">' in html
    assert '<div id="svelte-app"><div class=\'todo-app\'>hi</div></div>' in html
    assert '<script type="application/json" id="svelte-props">{"todos": []}</script>' in html
    assert '<script type="module" src="/dist/client/todos.A1B2.js">' in html


def test_props_are_html_safe():
    assets = RouteAssets(ssr="x", client="x.js", css=None, preload=[])
    html = build_html(
        body="",
        head_extra="",
        props={"x": "</script><script>alert(1)//"},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    # JSON.stringify-style escape: < and > and & inside JSON string
    assert "</script>" not in html.replace('<script type="module"', '').replace('<script type="application/json"', '').replace('</script>\n    <script', '')
    # specifically, the embedded value must not break out of the json script tag
    # check the raw json block
    start = html.index('id="svelte-props">') + len('id="svelte-props">')
    end = html.index('</script>', start)
    json_block = html[start:end]
    assert "<" not in json_block  # all < must be escaped to \u003c


def test_total_size_for_typical_page_under_5kb():
    assets = RouteAssets(
        ssr="ssr/todos.mjs",
        client="client/todos.A1B2.js",
        css="client/todos.A1B2.css",
        preload=[],
    )
    html = build_html(
        body="<div>" + ("a" * 1000) + "</div>",
        head_extra="<meta name='description' content='x'>",
        props={"a": 1},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    overhead = len(html) - 1000  # body content ~1KB
    assert overhead < 1500, f"HTML overhead {overhead}B is too large"
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/core/test_html.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/core/html.py`**

```python
"""Minimal HTML builder. Reads from manifest, produces response under 10KB."""
import json
from typing import Any, Dict
from fymo.build.manifest import RouteAssets


def _safe_json(obj: Any) -> str:
    """JSON serialize and escape for safe embedding in <script type=application/json>.

    Per HTML5: such a script's content must not contain `</script` (case-insensitive).
    We escape `<`, `>`, `&` to their \\uXXXX equivalents — JSON-compatible and safe.
    """
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_html(
    body: str,
    head_extra: str,
    props: Dict[str, Any],
    assets: RouteAssets,
    title: str,
    asset_prefix: str = "/dist",
) -> str:
    """Render the minimal HTML envelope. Pieces are concatenated with no boilerplate."""
    css_link = (
        f'<link rel="stylesheet" href="{asset_prefix}/{assets.css}">\n'
        if assets.css else ""
    )
    preload = "".join(
        f'<link rel="modulepreload" href="{asset_prefix}/{p}">\n'
        for p in assets.preload
    )
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"{head_extra}"
        f"{css_link}"
        f'<link rel="modulepreload" href="{asset_prefix}/{assets.client}">\n'
        f"{preload}"
        "</head>\n"
        "<body>\n"
        f'<div id="svelte-app">{body}</div>\n'
        f'<script type="application/json" id="svelte-props">{_safe_json(props)}</script>\n'
        f'<script type="module" src="{asset_prefix}/{assets.client}"></script>\n'
        "</body>\n"
        "</html>\n"
    )
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/core/test_html.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/html.py tests/core/test_html.py
git commit -m "feat(core): add minimal HTML builder with safe JSON embedding"
```

### Task 14: Static asset serving for /dist/<path>

**Files:**
- Modify: `fymo/core/assets.py`
- Modify: `fymo/core/server.py`
- Test: `tests/integration/test_dist_serving.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_dist_serving.py`:

```python
import io
import sys
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_dist_assets_served_with_immutable_caching(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")

    from fymo import create_app
    app = create_app(example_app)
    try:
        # find a hashed client bundle
        client_dir = example_app / "dist" / "client"
        bundle = next(client_dir.glob("todos.*.js"))
        rel = bundle.relative_to(example_app / "dist").as_posix()

        responses = []
        def start_response(status, headers):
            responses.append((status, headers))

        body = b"".join(app({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": f"/dist/{rel}",
            "QUERY_STRING": "",
            "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))

        assert responses[0][0].startswith("200")
        headers = dict(responses[0][1])
        assert "Cache-Control" in headers
        assert "immutable" in headers["Cache-Control"]
        assert headers.get("Content-Type", "").startswith("application/javascript")
        assert b"hydrate" in body
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_dist_path_traversal_rejected(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")

    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))
        body = b"".join(app({
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/dist/../../etc/passwd",
            "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))
        assert responses[0][0].startswith("404") or responses[0][0].startswith("403")
    finally:
        if app.sidecar:
            app.sidecar.stop()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/integration/test_dist_serving.py -v`
Expected: FAIL.

- [ ] **Step 3: Add `serve_dist_asset` to `fymo/core/assets.py`**

Add this method to `AssetManager`:

```python
    def serve_dist_asset(self, path: str) -> Tuple[bytes, str, str, Dict[str, str]]:
        """Serve a file from <project>/dist/. Returns (body, status, content_type, extra_headers).

        path: the part after /dist/ (e.g. "client/todos.A1B2.js")
        """
        import mimetypes
        # Reject obvious traversal attempts
        if ".." in path.split("/") or "\x00" in path:
            return b"forbidden", "403 FORBIDDEN", "text/plain", {}

        dist_root = (self.project_root / "dist").resolve()
        target = (dist_root / path).resolve()

        # Defense in depth: ensure target is still within dist_root after resolution
        try:
            target.relative_to(dist_root)
        except ValueError:
            return b"forbidden", "403 FORBIDDEN", "text/plain", {}

        if not target.is_file():
            return b"not found", "404 NOT FOUND", "text/plain", {}

        content_type, _ = mimetypes.guess_type(str(target))
        if content_type is None:
            content_type = "application/octet-stream"

        # Hashed filenames (anything in client/) get long-cache; manifest.json gets no-cache
        if path == "manifest.json":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"

        return target.read_bytes(), "200 OK", content_type, {"Cache-Control": cache}
```

Make sure the `Dict[str, str]` import is in scope (add to `from typing import` if not).

- [ ] **Step 4: Wire `/dist/...` in `fymo/core/server.py`**

In the WSGI handler, before the existing `/assets/` branch, add:

```python
        if path.startswith("/dist/"):
            rest = path[len("/dist/"):]
            body, status, content_type, headers = self.asset_manager.serve_dist_asset(rest)
            response_headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
            response_headers.extend(headers.items())
            start_response(status, response_headers)
            return [body]
```

- [ ] **Step 5: Run test — expect pass**

Run: `pytest tests/integration/test_dist_serving.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add fymo/core/assets.py fymo/core/server.py tests/integration/test_dist_serving.py
git commit -m "feat(core): serve /dist/<path> with content-hashed immutable caching"
```

### Task 15: Switch render path to use new HTML builder

**Files:**
- Modify: `fymo/core/template_renderer.py`
- Test: `tests/integration/test_request_flow.py` (extend)

- [ ] **Step 1: Add a test for HTML size**

Add to `tests/integration/test_request_flow.py`:

```python
@pytest.mark.usefixtures("node_available")
def test_response_html_under_10kb(example_app, monkeypatch):
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.setenv("FYMO_NEW_PIPELINE", "1")

    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": __import__("io").BytesIO(),
            "wsgi.errors": __import__("sys").stderr,
            "wsgi.url_scheme": "http",
        }, start_response))

        assert responses[0][0].startswith("200")
        assert len(body) < 10_000, f"response size {len(body)}B exceeds 10KB limit"
        # Must reference the bundle externally, not inline
        assert b'<script type="module" src="/dist/client/todos.' in body
        assert b'_fymo_packages' not in body  # old IIFE bundle inlining must be gone
    finally:
        if app.sidecar:
            app.sidecar.stop()
```

- [ ] **Step 2: Run — expect failure**

Run: `pytest tests/integration/test_request_flow.py::test_response_html_under_10kb -v`
Expected: FAIL — response still uses old big template.

- [ ] **Step 3: Update `_render_via_sidecar` in `fymo/core/template_renderer.py`**

Replace its body with:

```python
    def _render_via_sidecar(self, route_path: str) -> Tuple[str, str]:
        """New pipeline: render via Node sidecar with prebuilt SSR module."""
        from fymo.core.sidecar import SidecarError
        from fymo.core.manifest_cache import ManifestUnavailable
        from fymo.core.html import build_html

        route_info = self.router.match(route_path)
        if not route_info:
            return self._render_404(), "404 NOT FOUND"

        route_name = route_info["controller"]
        controller_module = f"app.controllers.{route_info['controller']}"
        _, props, doc_meta = self._load_controller_data(controller_module)

        try:
            manifest = self.manifest_cache.get()
        except ManifestUnavailable as e:
            return f"<div>Build error: {e}</div>", "500 INTERNAL SERVER ERROR"

        if route_name not in manifest.routes:
            return (
                f"<div>Route '{route_name}' not in manifest. Run `fymo build`.</div>",
                "500 INTERNAL SERVER ERROR",
            )

        try:
            ssr = self.sidecar.render(route_name, props)
        except SidecarError as e:
            return f"<div>SSR Error: {e}</div>", "500 INTERNAL SERVER ERROR"

        title = doc_meta.get("title", self.config_manager.get_app_name())
        head_extra = self._generate_head_content(doc_meta.get("head", {}))
        # Prepend Svelte's own <head> output
        head_extra = (ssr["head"] or "") + head_extra

        html = build_html(
            body=ssr["body"],
            head_extra=head_extra,
            props=props,
            assets=manifest.routes[route_name],
            title=title,
        )
        return html, "200 OK"
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/integration/test_request_flow.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/template_renderer.py tests/integration/test_request_flow.py
git commit -m "feat(core): emit minimal HTML referencing /dist assets via manifest"
```

### Task 16: Playwright hydration smoke test

**Files:**
- Create: `tests/integration/test_hydration_browser.py`
- Modify: `pyproject.toml` (add `playwright` extra)

- [ ] **Step 1: Add Playwright to dev extras**

In `pyproject.toml`, under `[project.optional-dependencies]`:

```toml
dev = [
    "pytest>=7.0",
    "pytest-playwright>=0.4.0",
    "playwright>=1.40.0",
    "black>=22.0",
    "flake8>=5.0",
    "mypy>=1.0",
]
```

Install: `pip install -e ".[dev]" && playwright install chromium`

- [ ] **Step 2: Write the test**

`tests/integration/test_hydration_browser.py`:

```python
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@contextmanager
def _serve(example_app: Path, port: int):
    proc = subprocess.Popen(
        ["python", "server.py"],
        cwd=example_app,
        env={**os.environ, "FYMO_NEW_PIPELINE": "1", "FYMO_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # wait for server
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.2)
            s.close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        out, err = proc.communicate(timeout=2)
        raise RuntimeError(f"server did not start: {out!r} {err!r}")

    try:
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.usefixtures("node_available")
def test_hydration_works_in_browser(example_app, page):
    BuildPipeline(project_root=example_app).build(dev=False)
    port = _free_port()
    with _serve(example_app, port):
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector(".todo-app")
        # Click the first todo's checkbox; if hydration is dead, this won't toggle the class
        page.locator("#todo-2").click()
        assert "completed" in (page.locator("li").nth(1).get_attribute("class") or "")
        # Console must be clean
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.reload()
        page.wait_for_selector(".todo-app")
        assert not errors, f"console errors: {errors}"
```

Note: this test requires `examples/todo_app/server.py` to honor `FYMO_PORT`. Check whether it does; if not, add this in Task 17 or a small follow-up.

- [ ] **Step 3: Run the test**

Run: `pytest tests/integration/test_hydration_browser.py -v -s`
Expected: 1 PASSED.

If it fails, debug:
- Check the served HTML with `curl http://127.0.0.1:<port>/`. It should match the minimal-HTML shape.
- Check `dist/client/todos.*.js` is loadable — `curl http://127.0.0.1:<port>/dist/client/todos.A1B2.js | head`.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_hydration_browser.py pyproject.toml
git commit -m "test: add Playwright smoke test verifying browser hydration"
```

---

## Phase 4 — `fymo dev` watcher

Goal of this phase: `fymo dev` watches `app/templates/`, runs incremental rebuilds, respawns the sidecar, and pushes SSE reload events to open browser tabs.

### Task 17: Node watch script with esbuild context

**Files:**
- Create: `fymo/build/js/dev.mjs`

- [ ] **Step 1: Write `fymo/build/js/dev.mjs`**

This script reuses the same build configuration but runs in watch mode and prints a JSON event line on each rebuild.

```javascript
#!/usr/bin/env node
import * as esbuild from 'esbuild';
import sveltePlugin from 'esbuild-svelte';
import fs from 'node:fs/promises';
import path from 'node:path';

const config = JSON.parse(process.argv[2]);

function emit(event) {
    process.stdout.write(JSON.stringify(event) + "\n");
}

async function makeServerCtx() {
    const entryPoints = Object.fromEntries(config.routes.map(r => [r.name, r.entryPath]));
    return await esbuild.context({
        entryPoints,
        outdir: path.join(config.distDir, 'ssr'),
        outExtension: { '.js': '.mjs' },
        format: 'esm',
        platform: 'node',
        bundle: true,
        splitting: false,
        minify: false,
        sourcemap: 'linked',
        metafile: true,
        plugins: [
            sveltePlugin({ compilerOptions: { generate: 'server', dev: false } }),
            { name: 'fymo-emit', setup(build) { build.onEnd(r => emit({ type: 'server-rebuild', errors: r.errors.map(e => e.text) })); } },
        ],
        logLevel: 'silent',
    });
}

async function makeClientCtx() {
    const entryPoints = Object.fromEntries(Object.entries(config.clientEntries));
    return await esbuild.context({
        entryPoints,
        outdir: path.join(config.distDir, 'client'),
        format: 'esm',
        platform: 'browser',
        bundle: true,
        splitting: true,
        entryNames: '[name].[hash]',
        chunkNames: 'chunk-[name].[hash]',
        assetNames: '[name].[hash]',
        minify: false,
        sourcemap: 'linked',
        metafile: true,
        plugins: [
            sveltePlugin({ compilerOptions: { generate: 'client', dev: false } }),
            { name: 'fymo-emit', setup(build) { build.onEnd(r => emit({ type: 'client-rebuild', errors: r.errors.map(e => e.text), metafile: r.metafile })); } },
        ],
        logLevel: 'silent',
    });
}

async function copySidecar() {
    const __dirname = path.dirname(new URL(import.meta.url).pathname);
    await fs.mkdir(config.distDir, { recursive: true });
    await fs.copyFile(path.join(__dirname, 'sidecar.mjs'), path.join(config.distDir, 'sidecar.mjs'));
}

await copySidecar();
const serverCtx = await makeServerCtx();
const clientCtx = await makeClientCtx();
await Promise.all([serverCtx.watch(), clientCtx.watch()]);
emit({ type: 'ready' });
```

- [ ] **Step 2: Smoke-test by hand**

```bash
cd /Users/bishwasbhandari/Projects/fymo/examples/todo_app
mkdir -p .fymo/entries
cat > .fymo/entries/todos.client.js <<'EOF'
import { hydrate } from 'svelte';
import Component from '../../app/templates/todos/index.svelte';
const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {};
hydrate(Component, { target: document.getElementById('svelte-app'), props });
EOF
node ../../fymo/build/js/dev.mjs '{"projectRoot":"'$PWD'","distDir":"'$PWD'/dist","routes":[{"name":"todos","entryPath":"'$PWD'/app/templates/todos/index.svelte"}],"clientEntries":{"todos":"'$PWD'/.fymo/entries/todos.client.js"}}' &
```

Expected: stdout streams `{"type":"server-rebuild","errors":[]}` then `{"type":"client-rebuild",...}` then `{"type":"ready"}`. Touch `app/templates/todos/index.svelte` and observe a fresh rebuild line.

Kill it: `kill %1`.

- [ ] **Step 3: Commit**

```bash
git add fymo/build/js/dev.mjs
git commit -m "feat(build): add Node watch script with esbuild context.watch"
```

### Task 18: Python dev orchestrator (watch + sidecar respawn)

**Files:**
- Create: `fymo/build/dev_orchestrator.py`
- Test: `tests/integration/test_dev_watcher.py`

- [ ] **Step 1: Write the test**

`tests/integration/test_dev_watcher.py`:

```python
import time
from pathlib import Path
import pytest
from fymo.build.dev_orchestrator import DevOrchestrator


@pytest.mark.usefixtures("node_available")
def test_orchestrator_writes_initial_manifest(example_app: Path):
    orch = DevOrchestrator(project_root=example_app)
    orch.start()
    try:
        # wait for first build to complete (max 15s)
        deadline = time.time() + 15
        while time.time() < deadline:
            if (example_app / "dist" / "manifest.json").exists():
                break
            time.sleep(0.1)
        else:
            pytest.fail("manifest never written")
    finally:
        orch.stop()


@pytest.mark.usefixtures("node_available")
def test_orchestrator_rebuilds_on_change(example_app: Path):
    orch = DevOrchestrator(project_root=example_app)
    orch.start()
    try:
        # wait for first build
        deadline = time.time() + 15
        while time.time() < deadline and not (example_app / "dist" / "manifest.json").exists():
            time.sleep(0.1)
        first_mtime = (example_app / "dist" / "manifest.json").stat().st_mtime

        # trigger rebuild
        target = example_app / "app" / "templates" / "todos" / "index.svelte"
        target.write_text(target.read_text() + "<!-- changed -->")

        deadline = time.time() + 10
        while time.time() < deadline:
            if (example_app / "dist" / "manifest.json").stat().st_mtime > first_mtime:
                return  # success
            time.sleep(0.1)
        pytest.fail("manifest mtime did not change after edit")
    finally:
        orch.stop()
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/integration/test_dev_watcher.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/build/dev_orchestrator.py`**

```python
"""Dev orchestrator: spawns Node watcher, parses its event stream, manages sidecar lifecycle."""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from fymo.build.discovery import discover_routes
from fymo.build.entry_generator import write_client_entries
from fymo.build.manifest import Manifest, RouteAssets


class DevOrchestrator:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.dist_dir = self.project_root / "dist"
        self.cache_dir = self.project_root / ".fymo" / "entries"
        self.dev_script = Path(__file__).resolve().parent / "js" / "dev.mjs"
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._listeners: List[Callable[[dict], None]] = []
        self._latest_metafile: Optional[dict] = None
        self._routes = []

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        """Register a callback invoked on every event from the watcher (e.g. SSE push)."""
        self._listeners.append(fn)

    def start(self) -> None:
        if shutil.which("node") is None:
            raise RuntimeError("node not found on PATH")
        templates = self.project_root / "app" / "templates"
        self._routes = discover_routes(templates)
        client_entries = write_client_entries(self._routes, self.cache_dir, self.project_root)

        config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": [{"name": r.name, "entryPath": str(r.entry_path)} for r in self._routes],
            "clientEntries": {n: str(p) for n, p in client_entries.items()},
        }
        self._proc = subprocess.Popen(
            ["node", str(self.dev_script), json.dumps(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.project_root),
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop_evt.is_set():
                return
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        if event.get("type") == "client-rebuild" and not event.get("errors"):
            self._latest_metafile = event.get("metafile")
            self._write_manifest()
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:
                pass

    def _write_manifest(self) -> None:
        if self._latest_metafile is None:
            return
        outputs = self._latest_metafile.get("outputs", {})
        client_by_route = {}
        css_by_route = {}
        chunks = []
        for out_path, info in outputs.items():
            try:
                rel = Path(out_path).resolve().relative_to(self.dist_dir.resolve()).as_posix()
            except ValueError:
                continue
            entry = info.get("entryPoint")
            if entry:
                for r in self._routes:
                    if Path(entry).name == f"{r.name}.client.js":
                        if rel.endswith(".js"):
                            client_by_route[r.name] = rel
                        elif rel.endswith(".css"):
                            css_by_route[r.name] = rel
            elif Path(out_path).name.startswith("chunk-") and rel.endswith(".js"):
                chunks.append(rel)

        routes = {}
        for r in self._routes:
            if r.name in client_by_route:
                routes[r.name] = RouteAssets(
                    ssr=f"ssr/{r.name}.mjs",
                    client=client_by_route[r.name],
                    css=css_by_route.get(r.name),
                    preload=chunks,
                )
        if routes:
            Manifest(
                routes=routes,
                build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ).write(self.dist_dir / "manifest.json")
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/integration/test_dev_watcher.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/build/dev_orchestrator.py tests/integration/test_dev_watcher.py
git commit -m "feat(build): add dev orchestrator with watch + manifest auto-update"
```

### Task 19: SSE reload and `fymo dev` CLI

**Files:**
- Create: `fymo/cli/commands/dev.py`
- Modify: `fymo/cli/main.py`
- Modify: `fymo/core/server.py` (SSE endpoint)
- Modify: `fymo/build/entry_generator.py` (append SSE listener in dev)
- Test: manual

- [ ] **Step 1: Add SSE endpoint to `fymo/core/server.py`**

In the WSGI handler, before `/dist/`:

```python
        if path == "/_dev/reload":
            return self._dev_sse(start_response)
```

Add the method:

```python
    def _dev_sse(self, start_response):
        """Server-sent events: push 'reload' on rebuild events from DevOrchestrator."""
        if self.dev_orchestrator is None:
            start_response("404 NOT FOUND", [("Content-Type", "text/plain")])
            return [b"not running in dev mode"]
        start_response("200 OK", [
            ("Content-Type", "text/event-stream"),
            ("Cache-Control", "no-cache"),
            ("Connection", "keep-alive"),
        ])
        from queue import Queue, Empty
        q: Queue = Queue()
        def listener(event):
            if event.get("type") in ("client-rebuild", "server-rebuild"):
                q.put("reload")
        self.dev_orchestrator.add_listener(listener)
        def stream():
            yield b"data: hello\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n".encode()
                except Empty:
                    yield b": keepalive\n\n"
        return stream()
```

Add `self.dev_orchestrator = None` to `FymoApp.__init__`.

- [ ] **Step 2: Update `fymo/build/entry_generator.py` to append SSE listener in dev**

Add a `dev: bool = False` parameter:

```python
def write_client_entries(
    routes: Iterable[Route],
    out_dir: Path,
    project_root: Path,
    dev: bool = False,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    sse_snippet = SSE_SNIPPET if dev else ""
    for route in routes:
        rel = os.path.relpath(route.entry_path, out_dir).replace(os.sep, "/")
        if not rel.startswith("."):
            rel = "./" + rel
        body = CLIENT_ENTRY_TEMPLATE.format(component_import=rel) + sse_snippet
        entry_path = out_dir / f"{route.name}.client.js"
        entry_path.write_text(body)
        written[route.name] = entry_path
    return written


SSE_SNIPPET = """
// Dev-only: live reload via SSE
if (typeof EventSource !== 'undefined') {
    const es = new EventSource('/_dev/reload');
    es.onmessage = (e) => { if (e.data === 'reload') location.reload(); };
}
"""
```

Update `DevOrchestrator.start()` and `BuildPipeline.build(dev=True)` to pass `dev=True`.

- [ ] **Step 3: Create `fymo/cli/commands/dev.py`**

```python
"""`fymo dev` — watch + serve."""
import os
import time
from pathlib import Path
from fymo.utils.colors import Color
from fymo.build.dev_orchestrator import DevOrchestrator


def run_dev(host: str = "127.0.0.1", port: int = 8000):
    project_root = Path.cwd()
    Color.print_info("Starting dev server with watcher")

    orch = DevOrchestrator(project_root=project_root)
    orch.start()

    # Wait for initial build
    manifest_path = project_root / "dist" / "manifest.json"
    deadline = time.time() + 30
    while time.time() < deadline and not manifest_path.exists():
        time.sleep(0.1)
    if not manifest_path.exists():
        Color.print_error("initial build did not complete in 30s")
        orch.stop()
        return

    Color.print_success("Initial build complete")

    os.environ["FYMO_NEW_PIPELINE"] = "1"

    from fymo import create_app
    app = create_app(project_root)
    app.dev_orchestrator = orch

    from wsgiref.simple_server import make_server
    server = make_server(host, port, app)
    Color.print_info(f"Listening on http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.sidecar:
            app.sidecar.stop()
        orch.stop()
```

- [ ] **Step 4: Wire `dev` command in `fymo/cli/main.py`**

```python
@cli.command(name="dev")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def dev_cmd(host, port):
    """Start dev server with file watcher."""
    from fymo.cli.commands.dev import run_dev
    run_dev(host=host, port=port)
```

- [ ] **Step 5: Manual smoke test**

```bash
cd /Users/bishwasbhandari/Projects/fymo/examples/todo_app
fymo dev
# in another terminal
curl -s http://127.0.0.1:8000/ | head -5
# edit app/templates/todos/index.svelte; observe rebuild + browser refresh
```

Expected: page loads, edits trigger reload within < 1s.

- [ ] **Step 6: Commit**

```bash
git add fymo/cli/commands/dev.py fymo/cli/main.py fymo/core/server.py fymo/build/entry_generator.py
git commit -m "feat(cli): add fymo dev with SSE-based browser reload"
```

### Task 20: Sidecar respawn on rebuild

**Files:**
- Modify: `fymo/cli/commands/dev.py`
- Modify: `fymo/core/manifest_cache.py` (no change needed — mtime detection already works)

- [ ] **Step 1: Make orchestrator notify Python to respawn sidecar after server rebuild**

Update `run_dev` in `fymo/cli/commands/dev.py`:

```python
def run_dev(host: str = "127.0.0.1", port: int = 8000):
    project_root = Path.cwd()
    Color.print_info("Starting dev server with watcher")

    orch = DevOrchestrator(project_root=project_root)
    orch.start()

    manifest_path = project_root / "dist" / "manifest.json"
    deadline = time.time() + 30
    while time.time() < deadline and not manifest_path.exists():
        time.sleep(0.1)
    if not manifest_path.exists():
        Color.print_error("initial build did not complete in 30s")
        orch.stop()
        return

    os.environ["FYMO_NEW_PIPELINE"] = "1"
    from fymo import create_app
    app = create_app(project_root)
    app.dev_orchestrator = orch

    def on_rebuild(event):
        if event.get("type") == "server-rebuild" and not event.get("errors") and app.sidecar:
            try:
                app.sidecar.stop()
                app.sidecar.start()
                app.sidecar.ping()
            except Exception as e:
                Color.print_error(f"sidecar respawn failed: {e}")
    orch.add_listener(on_rebuild)

    from wsgiref.simple_server import make_server
    server = make_server(host, port, app)
    Color.print_info(f"Listening on http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.sidecar:
            app.sidecar.stop()
        orch.stop()
```

- [ ] **Step 2: Verify by hand**

Same as Task 19 step 5. Edit a `.svelte`, confirm `fymo dev` logs no error and the page reflects changes after reload.

- [ ] **Step 3: Commit**

```bash
git add fymo/cli/commands/dev.py
git commit -m "feat(dev): respawn sidecar after server rebuild to bust ESM module cache"
```

---

## Phase 5 — Cleanup

Goal of this phase: flip the default to the new pipeline and delete the old code.

### Task 21: Flip default and remove flag

**Files:**
- Modify: `fymo/core/server.py`
- Modify: `fymo/cli/commands/build.py`

- [ ] **Step 1: Remove `FYMO_NEW_PIPELINE` gate from `fymo/core/server.py`**

Replace the conditional sidecar init with unconditional init (assuming `dist/sidecar.mjs` exists):

```python
        from fymo.core.sidecar import Sidecar
        from fymo.core.manifest_cache import ManifestCache
        dist_dir = project_root / "dist"
        if (dist_dir / "sidecar.mjs").is_file():
            self.sidecar = Sidecar(dist_dir=dist_dir)
            self.sidecar.start()
            self.sidecar.ping()
            self.manifest_cache = ManifestCache(dist_dir=dist_dir)
            self.template_renderer.sidecar = self.sidecar
            self.template_renderer.manifest_cache = self.manifest_cache
        else:
            raise RuntimeError(
                f"dist/ not found at {dist_dir}. Run `fymo build` (or `fymo dev`) first."
            )
```

- [ ] **Step 2: Simplify `fymo/cli/commands/build.py`**

Replace `build_project` body with the new pipeline (no flag check):

```python
def build_project(output: str = 'dist', minify: bool = False):
    project_root = Path.cwd()
    Color.print_info("Building")
    try:
        BuildPipeline(project_root=project_root).build(dev=False)
    except BuildError as e:
        Color.print_error(str(e))
        raise SystemExit(1)
    Color.print_success(f"Built to {project_root / 'dist'}/")
```

- [ ] **Step 3: Update `fymo/cli/commands/build.py:build_runtime` (legacy command)**

Make it a no-op that prints a deprecation note:

```python
def build_runtime():
    Color.print_info("`fymo build-runtime` is deprecated; the runtime is bundled per-route by `fymo build`.")
    return True
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: all PASSED. (Note: `test_fymo_build_without_flag_keeps_old_path` from Task 9 will now fail. Delete that test.)

```bash
# Delete the obsolete test
sed -i '' '/test_fymo_build_without_flag_keeps_old_path/,/^$/d' tests/integration/test_cli_build.py
pytest tests/ -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/server.py fymo/cli/commands/build.py tests/integration/test_cli_build.py
git commit -m "refactor: make new pipeline the default; drop FYMO_NEW_PIPELINE flag"
```

### Task 22: Delete legacy code

**Files:**
- Delete: `fymo/core/runtime.py`
- Delete: `fymo/core/bundler.py`
- Delete: `fymo/core/component_resolver.py`
- Delete: `fymo/core/compiler.py`
- Delete: `fymo/bundler/` (entire directory)
- Delete: `fymo/core/utils/` (entire directory if only used by deleted files — verify first)
- Modify: `fymo/core/template_renderer.py` (remove legacy code path, imports)
- Modify: `fymo/core/assets.py` (remove `_serve_svelte_runtime`, `_serve_svelte_runtime_path`, `store_compiled_component`, `get_compiled_component`)
- Modify: `pyproject.toml` (remove `stpyv8` from dependencies)
- Modify: `requirements.txt`

- [ ] **Step 1: Find all imports of doomed modules**

```bash
grep -rn "from fymo.core.runtime\|from fymo.core.bundler\|from fymo.core.compiler\|from fymo.core.component_resolver\|from fymo.bundler\|import STPyV8\|stpyv8" fymo/ examples/ tests/
```

Expected: only `template_renderer.py` and `cli/commands/build.py` reference these. No other dependents.

- [ ] **Step 2: Strip legacy path from `template_renderer.py`**

Open `fymo/core/template_renderer.py`. Delete:
- imports of `SvelteCompiler`, `JSRuntime`
- `self.compiler = SvelteCompiler(...)`, `self.runtime = JSRuntime()` from `__init__`
- The `else:` branch in `render_template` that calls `compiler.compile_ssr` etc.
- `_compile_for_hydration`, the legacy `_generate_html_page` (or keep it but remove the unused branches)

The renderer now has only the sidecar+manifest path.

- [ ] **Step 3: Strip legacy serving from `assets.py`**

Delete:
- `_serve_svelte_runtime`, `_serve_svelte_runtime_path`, `_candidate_runtime_paths`, `_read_runtime`
- `compiled_components: Dict[str, str]`, `store_compiled_component`, `get_compiled_component`
- The `elif asset_path == 'svelte-runtime.js'` and `elif asset_path.startswith('svelte/')` branches in `serve_asset`

- [ ] **Step 4: Delete files and directory**

```bash
git rm fymo/core/runtime.py fymo/core/bundler.py fymo/core/component_resolver.py fymo/core/compiler.py
git rm -r fymo/bundler
# Inspect fymo/core/utils — keep what html.py uses, delete the rest
ls fymo/core/utils/
```

Inspect `fymo/core/utils/` files. They were used by the legacy runtime; if grep shows zero remaining references, delete them too:

```bash
grep -rn "fymo.core.utils" fymo/
# if empty:
git rm -r fymo/core/utils
```

- [ ] **Step 5: Remove STPyV8 from `pyproject.toml`**

Edit dependencies array, delete the `"stpyv8>=13.1.201.22"` line. Also from `requirements.txt`.

- [ ] **Step 6: Verify install + tests**

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Expected: install succeeds without STPyV8; all tests PASSED.

- [ ] **Step 7: Commit**

```bash
git add -u
git commit -m "refactor: delete legacy V8 runtime, regex bundler, and STPyV8 dependency"
```

### Task 23: Update README and example app

**Files:**
- Modify: `README.md`
- Modify: `examples/todo_app/README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Update root `README.md`**

Replace the "Quick Start" section to reflect:
- `npm install` for esbuild + esbuild-svelte (still required)
- `fymo build` produces `dist/`
- `fymo serve` (or `fymo dev` for watch mode)
- No more `fymo build-runtime` (deprecated)

Show the new minimal HTML shape in the "Features" section.

- [ ] **Step 2: Update `examples/todo_app/README.md`**

Update the "Quick Start" to:

```markdown
## Quick Start

### 1. Install Dependencies
pip install -r requirements.txt
npm install

### 2. Build
fymo build

### 3. Serve
fymo serve   # production-like
# or
fymo dev     # watch mode with auto-rebuild
```

- [ ] **Step 3: Update `.gitignore`**

Add:

```
dist/
.fymo/
```

- [ ] **Step 4: End-to-end smoke**

```bash
cd examples/todo_app
fymo build
fymo serve &
SERVER_PID=$!
sleep 3
SIZE=$(curl -sS http://127.0.0.1:8000/ | wc -c)
echo "HTML size: $SIZE bytes"
kill $SERVER_PID
```

Expected: HTML size < 10000 bytes.

- [ ] **Step 5: Commit**

```bash
git add README.md examples/todo_app/README.md .gitignore
git commit -m "docs: update README for build-time pipeline workflow"
```

---

## Self-review checklist (run after writing the plan)

- [x] Spec section 3 (Architecture) — covered by Tasks 6, 7, 8, 10
- [x] Spec section 4 (Build pipeline) — covered by Tasks 2-9
- [x] Spec section 5 (Sidecar) — covered by Tasks 6 (sidecar.mjs), 10 (Python client)
- [x] Spec section 6 (HTML output) — covered by Tasks 13, 15
- [x] Spec section 7 (Static asset serving) — covered by Task 14
- [x] Spec section 8 (Errors) — covered by sidecar error handling in Task 10, render error path in Task 12, build error path in Tasks 8-9, dev error overlay (deferred — see Open Items)
- [x] Spec section 9 (Rollout) — phases map 1:1 to plan phases
- [ ] **Open Items / followups not in this plan** (acceptable — these are spec section 10 risks, addressed pragmatically):
  - Dev error overlay UI (today: serves a plain `<div>Build error:</div>`). Improvement: render a structured overlay. Tracked as future enhancement.
  - Worker pool for sidecar concurrency (single-flight is fine for v1 per spec section 10.4).
  - File-based routing — explicit non-goal in spec section 11.
  - HMR with state preservation — explicit non-goal.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-28-fymo-build-pipeline.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for a plan this large (23 tasks across 5 phases).

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
