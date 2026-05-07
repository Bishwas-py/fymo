---
title: SvelteKit-style wire format for Fymo Remote Functions
date: 2026-04-28
status: approved-design
authors: Bishwas
related: docs/superpowers/specs/2026-04-28-fymo-remote-functions-design.md
---

# SvelteKit-style wire format for Fymo Remote Functions

## 1. Context

Fymo Remote Functions shipped (commit `9ac50f4`) with a serviceable but minimal wire format:

- `POST /__remote/<module>/<fn_name>`
- Body: `{"args": [...]}` as plain JSON
- Response: `{"ok": true, "data": ...}` (HTTP 200) or `{"ok": false, "error": ...}` (HTTP 4xx/5xx)
- No CSRF protection beyond `SameSite=Lax` cookie
- `datetime` becomes a string; `Map`/`Set`/`undefined` are unrepresentable

After reading SvelteKit's actual remote-function source (`packages/kit/src/runtime/server/remote.js`, `runtime/client/remote-functions/*`, `runtime/shared.js`), three specific differences stand out:

1. **Wire format.** SvelteKit uses [devalue](https://github.com/Rich-Harris/devalue) — a tagged JSON dialect that preserves `Date`, `Map`, `Set`, `BigInt`, `RegExp`, `undefined`, repeated references, and (via the `transport` hook) custom classes. Args are devalue-stringified, base64url-encoded, and put on the wire.

2. **URLs are hashed.** Endpoints are `/<base>/<app_dir>/remote/<HASH>/<fn_name>` where `HASH` is a build-time identifier of the source `.remote.js` file. Functions can't be enumerated by guessing module names.

3. **Responses are always 200 OK** with a discriminated `type` field: `"result" | "error" | "redirect"`. Status codes ride inside the body. CSRF is enforced by an `Origin === Host` check before the handler runs.

This spec adopts those three properties without restructuring the rest of Fymo Remote Functions. Function definitions in `app/remote/*.py`, the `$remote/<name>` import resolver, prop-threading via `getContext`, and the codegen pipeline all stay. Only the wire boundary changes.

## 2. Goals & non-goals

**Goals**

- Wire-level interoperability with SvelteKit's remote-function shape: same URL pattern, same body format, same response envelope.
- Devalue serialization in both directions, so `Date`, `Map`, `Set`, `BigInt`, `undefined`, repeated references, `Decimal`, `UUID`, `Enum`, and `bytes` round-trip with full type fidelity.
- CSRF protection via `Origin === Host` check at the WSGI router.
- Build-time hash per `app/remote/*.py` module, baked into emitted client stubs and into the SSR-emitted `__fymo_remote` markers. Functions become unreachable unless their hash leaked into a rendered page.
- App-author code (component imports, controller `getContext()` returns, remote function definitions) stays bit-for-bit identical. Only generated artifacts and the WSGI router change.

**Non-goals**

- Function kinds (`@query`/`@form`/`@command`/`@prerender`). v2.
- Query batching (multiple queries collapsed into one HTTP request). v2.
- Single-flight mutations (`refresh()`, `set()`, `requested()`). v2.
- User-facing `transport` hook API for registering custom encoders. The infrastructure exists internally; the public surface comes later.
- `.fields.x.as('text')` form helpers, progressive enhancement of HTML forms. v2.
- Dedup of identical query calls within the same render. v2.
- Real authentication (`fymo_uid` is still an opaque identity token, not a credential).

## 3. Architecture

```
┌──────────────────────────────────┐  build-time
│ app/remote/posts.py              │  ─── hashlib.sha256(file_content)[:12] → "4f3a9c1b8e2d"
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────────────────────────────────┐
│ dist/manifest.json                                           │
│   "remote_modules": {                                        │
│     "posts": {                                               │
│       "hash": "4f3a9c1b8e2d",                                │
│       "fns": ["get_posts","create_comment","toggle_reaction"]│
│     }                                                        │
│   }                                                          │
└──────────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ dist/client/_remote/posts.js     │    │ dist/client/_remote/posts.d.ts   │
│   const HASH = '4f3a9c1b8e2d';   │    │   (unchanged — types only)       │
│   export const get_posts = (...) │    │                                  │
│     => __rpc(HASH, 'get_posts',  │    │                                  │
│              args);              │    │                                  │
└──────────────────────────────────┘    └──────────────────────────────────┘
               │
               ▼
        Client calls __rpc("4f3a9c1b8e2d", "create_comment", [slug, input])
               │
               ▼
        POST /_fymo/remote/4f3a9c1b8e2d/create_comment
        Origin: https://yoursite.example.com
        Body: {"payload": "<base64url(devalue.stringify([slug, input]))>"}
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│ fymo/remote/router.py                                        │
│   1. Origin === Host? else 200 + {type:"error",status:403}   │
│   2. Resolve hash → module via manifest                      │
│   3. base64-decode payload, devalue.parse → args             │
│   4. validate_args (pydantic where typed)                    │
│   5. ensure_uid → cookie                                     │
│   6. request_scope: fn(*args) → result                       │
│   7. devalue.stringify(result) → response result string      │
└──────────────────────────────────────────────────────────────┘
               │
               ▼
        HTTP 200 OK
        Body: {"type":"result","result":"<devalue-string>"}
               │
               ▼
        Client devalue.parse(result) → real Date / Map / Set
```

**Five separations of concern** (mostly the same as v0; only the marked rows change):

| Concern | Where | Changed? |
|---|---|---|
| Function discovery + introspection | `fymo/remote/discovery.py` | + file hash |
| Type bridge (Python → TS) | `fymo/remote/typemap.py` | unchanged |
| Codegen (.js + .d.ts) | `fymo/remote/codegen.py` | bake hash into .js |
| HTTP wire format | `fymo/remote/router.py`, `__runtime.js` | **rewritten** |
| Wire serialization | `fymo/remote/adapters.py` (now `devalue.py`) | **rewritten** |
| SSR callable serialization | `fymo/core/html.py` | marker carries hash |
| Identity / request scope | `fymo/remote/identity.py`, `context.py` | unchanged |

## 4. Wire protocol

### 4.1 URL

```
POST /_fymo/remote/<HASH>/<FN_NAME>
```

- `HASH`: 12-character lowercase hex prefix of `sha256(file_content)` of the source `app/remote/<module>.py` file.
- `FN_NAME`: validated as `[A-Za-z0-9_]+`, not starting with `_`.
- Routing prefix `/_fymo/` is dedicated and never collides with app routes.

### 4.2 Request body

```json
{"payload": "<BASE64URL_OF_DEVALUE_STRING>"}
```

- `payload` is `args` array (a JSON array of positional arguments) → `devalue.stringify(args)` → base64url encoding (`+` → `-`, `/` → `_`, no padding).
- Empty-args calls send `{"payload": "<encoding of []>"}`.

### 4.3 Response (always HTTP 200)

```json
// Success
{"type": "result", "result": "<devalue-string>"}

// Domain or validation error
{"type": "error", "status": 422, "error": "validation", "issues": [...]}
{"type": "error", "status": 404, "error": "not_found", "message": "..."}
{"type": "error", "status": 403, "error": "cross_origin"}
{"type": "error", "status": 500, "error": "internal", "message": "..."}

// Redirect (raised via fymo.remote.Redirect, v1 supports but no use in current blog)
{"type": "redirect", "location": "/login"}
```

The HTTP status code is **always 200**. The application-level outcome is in `type`. Client `__rpc` switches on `type`:
- `result` → `devalue.parse(payload.result)` and return.
- `error` → throw `Error` with `.status`, `.error`, `.issues` populated.
- `redirect` → `window.location.href = payload.location`.

### 4.4 CSRF guard

Before any function lookup or body parse, the router checks:

```python
origin = environ.get("HTTP_ORIGIN", "")
host = environ.get("HTTP_HOST", "")
scheme = environ.get("wsgi.url_scheme", "http")

if origin and host:
    expected = f"{scheme}://{host}"
    if origin != expected:
        return _200_with({"type": "error", "status": 403, "error": "cross_origin"})
```

Missing `Origin` (curl, server-to-server) is allowed. Mismatched (`Origin: https://evil.com` to `Host: yoursite.com`) is rejected. This matches SvelteKit's `respond.js` check.

## 5. devalue port (`fymo/remote/devalue.py`)

A Python implementation of devalue's wire format. Spec follows from devalue's source — a tagged JSON array.

### 5.1 Encoding rules

```
stringify(value) → JSON array of values, with index 0 holding the root reference

Tagged forms (encoded as 2-element arrays):
  ["Date", "<ISO-8601>"]
  ["Map",  [k_idx, v_idx, k_idx, v_idx, ...]]      # alternating key/value indices
  ["Set",  [item_idx, item_idx, ...]]
  ["BigInt", "<digits>"]
  ["RegExp", "<source>", "<flags>"]
  ["null"]                                          # null as object marker (vs JSON null)

Sentinels:
  -1   →  undefined
  -2   →  null
  -3   →  NaN
  -4   →  Infinity
  -5   →  -Infinity
  -6   →  0
```

Repeated values are deduplicated by Python `id()` (or value equality for hashable primitives) and stored once.

### 5.2 Python types and their devalue mapping

| Python | devalue tag | Reconstructed JS type |
|---|---|---|
| `str` | inline string | `string` |
| `int`, `float` | inline number | `number` |
| `bool` | inline boolean | `boolean` |
| `None` | sentinel `-2` | `null` |
| `bytes` | inline base64 string | `string` (caller decodes) |
| `datetime`, `date` | `["Date", iso]` | `Date` |
| `Decimal` | inline number | `number` |
| `UUID` | inline string | `string` |
| `Enum` | inline value | primitive |
| `set`, `frozenset` | `["Set", [...]]` | `Set` |
| `tuple` | array (no tag) | `Array` |
| `dict` | inline object | `Object` (or `Map` if requested via transport) |
| pydantic `BaseModel` | `model_dump(mode="python")` then encode the dict | `Object` |
| Other | `["__custom__", name, encoded]` if registered in transport, else raise | varies |

### 5.3 API

```python
# fymo/remote/devalue.py
def stringify(value: Any, transport: dict[str, tuple[Callable, Callable]] | None = None) -> str: ...
def parse(s: str, transport: dict[str, tuple[Callable, Callable]] | None = None) -> Any: ...
```

`transport` is a dict of `{type_name: (encode_fn, decode_fn)}`. v1 doesn't expose this to user code; the dict is constructed internally by the router and includes default encoders for `datetime`, `Decimal`, `UUID`, `bytes`, `Enum`. v2 adds a public registration API.

### 5.4 Edge cases

- **Cyclic references:** detect via a `visited: dict[id, idx]` map during encoding; emit reference indices, never duplicate. Stack-safe iterative encoder for deeply-nested values.
- **Pydantic models:** call `model_dump(mode="python")` first to get a dict, then encode the dict.
- **Unsupported types:** raise `TypeError` at encode time with a clear message naming the field path.

## 6. Hash strategy

```python
# fymo/remote/discovery.py
import hashlib
from pathlib import Path

def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
```

- Hash the **file contents**, not the module name. Same source produces the same hash; any change invalidates.
- 12 hex chars = 48 bits of collision space — fine for a typical app's handful of remote modules. Collision detection isn't necessary at this scale; if two modules ever produced the same hash, the manifest would expose it and the build would fail.
- Hash is stable across builds for unchanged source — useful for CDN caching of bundles.

The hash is stored in the manifest:

```json
{
  "remote_modules": {
    "posts": {
      "hash": "4f3a9c1b8e2d",
      "fns": ["get_posts", "get_post", "create_comment", "toggle_reaction"]
    }
  }
}
```

The router uses this manifest to map `<HASH>` back to a module name at request time. The manifest is the only place the mapping lives — the URL itself is opaque.

## 7. Codegen changes

### 7.1 Generated `.js`

```js
// dist/client/_remote/posts.js  (build-emitted)
import { __rpc } from './__runtime.js';
const HASH = '4f3a9c1b8e2d';
export const get_posts        = (...args) => __rpc(HASH, 'get_posts',        args);
export const create_comment   = (...args) => __rpc(HASH, 'create_comment',   args);
export const toggle_reaction  = (...args) => __rpc(HASH, 'toggle_reaction',  args);
```

The hash is baked in as a `const` rather than re-derived on every call. Re-builds with unchanged source produce byte-identical files (cacheable).

### 7.2 Generated `.d.ts`

Unchanged. Type signatures and interface declarations don't depend on URL shape.

### 7.3 Client runtime `__runtime.js`

```js
// dist/client/_remote/__runtime.js
import { stringify, parse } from 'devalue';

const REMOTE_MARKER = '__fymo_remote';

export async function __rpc(hash, name, args) {
    const url = `/_fymo/remote/${hash}/${name}`;
    const payload = b64url(stringify(args));
    const res = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload }),
    });
    let env;
    try { env = await res.json(); }
    catch { throw new Error('invalid response from ' + url); }
    if (env.type === 'redirect') { window.location.href = env.location; return; }
    if (env.type === 'error') {
        const e = new Error(env.error);
        e.status = env.status; e.error = env.error; e.issues = env.issues;
        throw e;
    }
    return parse(env.result);
}

export function __resolveRemoteProps(props) {
    for (const key in props) {
        const v = props[key];
        if (v && typeof v === 'object' && v[REMOTE_MARKER]) {
            const [hash, name] = v[REMOTE_MARKER].split('/');
            props[key] = (...args) => __rpc(hash, name, args);
        }
    }
    return props;
}

function b64url(s) {
    return btoa(s).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
}
```

The same logic is inlined into `fymo/build/entry_generator.py:CLIENT_ENTRY_TEMPLATE` (so apps with no remote modules still hydrate without depending on the runtime file existing).

### 7.4 SSR marker shape

```python
# fymo/core/html.py
def _remote_marker(obj):
    mod_name = obj.__module__
    if mod_name and mod_name.startswith("app.remote.") and callable(obj):
        short = mod_name[len("app.remote."):]
        hash = _MANIFEST_CACHE.get_remote_hash(short)
        return {"__fymo_remote": f"{hash}/{obj.__name__}"}
    raise TypeError(f"...")
```

The manifest is loaded at app startup (already in `fymo/core/manifest_cache.py`); we extend `ManifestCache` with a `get_remote_hash(module_name)` accessor.

## 8. WSGI router (`fymo/remote/router.py` rewrite)

```python
def handle_remote(environ, start_response):
    # 1. Origin check
    if not _origin_ok(environ):
        return _200_envelope(start_response, {"type": "error", "status": 403, "error": "cross_origin"})

    # 2. Parse path
    path = environ.get("PATH_INFO", "")
    parts = path[len("/_fymo/remote/"):].split("/")
    if len(parts) != 2:
        return _200_envelope(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    hash, fn_name = parts

    # 3. Manifest lookup
    module_name = _MANIFEST_CACHE.module_for_hash(hash)
    if module_name is None:
        return _200_envelope(start_response, {"type": "error", "status": 404, "error": "unknown_module"})

    # 4. Resolve fn (existing _resolve logic, scoped to the resolved module)
    fn, sig, hints = _resolve(module_name, fn_name)
    if fn is None:
        return _200_envelope(start_response, {"type": "error", "status": 404, "error": "unknown_function"})

    # 5. Decode payload
    try:
        body = json.loads(environ["wsgi.input"].read(_MAX_BODY))
        payload_b64 = body.get("payload", "")
        payload_str = _b64url_decode(payload_b64)
        args = devalue.parse(payload_str)
        if not isinstance(args, list):
            raise ValueError("payload must devalue-parse to a list")
    except Exception as e:
        return _200_envelope(start_response, {"type": "error", "status": 400, "error": "bad_payload", "message": str(e)})

    # 6. Validate (existing pydantic + stdlib path)
    try:
        validated = validate_args(args, sig, hints)
    except pydantic.ValidationError as e:
        return _200_envelope(start_response, {"type": "error", "status": 422, "error": "validation", "issues": e.errors()})
    except Exception as e:
        return _200_envelope(start_response, {"type": "error", "status": 422, "error": "validation", "message": str(e)})

    # 7. Identity + dispatch
    uid, set_cookie = _ensure_uid(environ)
    try:
        with request_scope(uid=uid, environ=environ):
            result = fn(*validated)
    except RemoteError as e:
        return _200_envelope(start_response, {"type": "error", "status": e.status, "error": e.code, "message": str(e)}, set_cookie)
    except Exception as e:
        return _200_envelope(start_response, {"type": "error", "status": 500, "error": "internal", "message": str(e), "traceback": traceback.format_exc()}, set_cookie)

    # 8. Encode response
    try:
        encoded = devalue.stringify(result)
    except Exception as e:
        return _200_envelope(start_response, {"type": "error", "status": 500, "error": "encode_failed", "message": str(e)}, set_cookie)

    return _200_envelope(start_response, {"type": "result", "result": encoded}, set_cookie)
```

`_200_envelope(start_response, payload, set_cookie=None)` always emits `200 OK` with `Content-Type: application/json` and the optional `Set-Cookie` header.

## 9. Migration impact

| Surface | Before | After |
|---|---|---|
| App-author Python in `app/remote/*.py` | unchanged | unchanged |
| App-author Svelte `import from '$remote/...'` | unchanged | unchanged |
| App-author controller `getContext` returning callables | unchanged | unchanged |
| Generated `.d.ts` types | unchanged | unchanged |
| Generated `.js` runtime path | `__runtime.js` reads hash-less marker | reads hash-prefixed marker |
| Wire URL | `/__remote/posts/create_comment` | `/_fymo/remote/<hash>/create_comment` |
| Wire body shape | `{args: [...]}` (plain JSON) | `{payload: "<base64url-devalue>"}` |
| Wire response shape | `{ok, data}` (HTTP 4xx on error) | `{type, result/error/status, ...}` (HTTP 200 always) |
| `examples/blog_app/` source | unchanged | unchanged |

Tests that asserted the old wire shape change. The blog example renders identically.

## 10. Rollout phases

| Phase | Output |
|---|---|
| **A. Python devalue port** | `fymo/remote/devalue.py` + `tests/remote/test_devalue.py` (15+ round-trip cases). 250 lines + tests. |
| **B. Hash discovery + manifest** | `fymo/remote/discovery.py` adds `file_hash`. `BuildPipeline` writes hash into manifest. `ManifestCache` exposes `module_for_hash`/`get_remote_hash`. |
| **C. Codegen update** | `fymo/remote/codegen.py` emits hash-baked `.js`. `__runtime.js` template rewritten to use devalue + new wire envelope. Marker shape in `fymo/core/html.py:_remote_marker` includes hash. |
| **D. Router rewrite** | `fymo/remote/router.py` accepts new URL pattern, decodes via devalue, returns 200-with-envelope. Origin check at top. |
| **E. Client runtime** | Add `devalue@^5` to framework `package.json`. Update `fymo/build/entry_generator.py:CLIENT_ENTRY_TEMPLATE` (inline copy). |
| **F. Test migration** | Update integration tests for new URL + body + response shape. Run blog e2e to confirm zero source change in `examples/blog_app/`. |

Phases A and B can run in parallel. C–F serialize.

## 11. Tests

- `tests/remote/test_devalue.py`: round-trip cases for primitives, nested dicts, lists, tuples, sets, frozensets, `None`, `datetime`, `date`, `Decimal`, `UUID`, `Enum`, `bytes`, repeated references (dedup), pydantic models, `undefined` sentinel.
- `tests/remote/test_router.py`: extend with — same-origin POST passes, cross-origin POST returns 200 with `{type:"error", status:403}`, missing-Origin POST passes, hash mismatch returns 404, validation error returns 200 with `type:"error", status:422`, RemoteError returns 200 with the right status field.
- `tests/integration/test_remote_e2e.py`: assert the new URL pattern in generated stubs.
- `tests/integration/test_blog_e2e.py`: extend to assert that a `Date` returned from `get_post` arrives client-side as a `Date` instance.

## 12. Acceptance criteria

- `fymo build` produces `dist/manifest.json` with `remote_modules.<name>.hash` populated.
- A page that imports `$remote/posts` ships a bundle whose URLs are of the form `/_fymo/remote/<12-hex>/<fn_name>`.
- A `curl -X POST http://localhost:8000/_fymo/remote/<HASH>/<FN> -H 'Origin: https://evil.example.com' -d '{"payload":""}'` returns HTTP 200 with `{"type":"error","status":403,"error":"cross_origin"}`.
- A remote function returning `datetime.now()` appears client-side as a real `Date` (`p.published_at instanceof Date === true`).
- The blog example renders identically to before (same HTML, same interactions). Zero source changes in `examples/blog_app/`.
- All 84 prior tests pass; ~25 new tests pass.

## 13. Open questions / risks

1. **Hash collision.** 48 bits = ~16M; for a project with <10 remote modules, the birthday-paradox probability of a collision is < 10⁻¹². If we ever observe one, the manifest writer can detect it (two modules with the same hash) and fail the build. Document the rule.
2. **devalue compatibility versions.** SvelteKit pins devalue major. We pin `devalue@^5` (the current major as of 2026-04). Spec doesn't track minor changes; if devalue@6 ships and changes the format, it's a v2 upgrade.
3. **Browser BigInt support.** Modern (>= 2020) browsers all have it. If a project targets older browsers, `bigint` gracefully degrades to `string` via the transport hook. Out of scope for v1.
4. **Reading the manifest at WSGI startup.** If the user starts the server before running `fymo build`, the manifest is missing — startup raises a clear error. Documented in the release notes.

## 14. Out of scope (v2 list)

- Function kinds (`@query`/`@form`/`@command`/`@prerender`)
- Query batching
- Single-flight mutations
- Public `transport` registration API for custom classes
- Form progressive enhancement
- Client-side query cache / dedup
- Streaming responses
- Hash collision detection in the manifest writer (we'll add it when it actually matters)
