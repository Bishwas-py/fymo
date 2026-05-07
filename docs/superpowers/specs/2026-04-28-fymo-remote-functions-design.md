---
title: Fymo Remote Functions + blog showcase
date: 2026-04-28
status: approved-design
authors: Bishwas
---

# Fymo Remote Functions + blog showcase

## 1. Context

Fymo today is one-way: controllers compute `getContext()` server-side, props are SSR'd into the page, the client hydrates. There is no defined way for the client to send anything back to the server. Adding state requires devs to invent their own fetch + endpoint glue per app, which means every Fymo app reinvents JSON serialization, validation, error handling, cookie plumbing, and the path/method conventions.

This spec adds **Fymo Remote Functions** — a flagship feature that lets devs write plain Python functions in `app/remote/*.py` and call them from Svelte components as if they were local. The Python type system flows through to TypeScript on the client, validated in production via pydantic where opted in, with a single uniform HTTP wire format.

The **blog example** ships with the framework feature both as proof and as the canonical demo: it consumes every part of the new API surface (typed reads, validated writes, `$props()`-threaded callables, direct `$remote/...` imports, cookie-based identity, TypeScript components).

## 2. Goals & non-goals

**Goals**

- **Plain functions, not RPC.** `def create_comment(slug: str, input: NewComment) -> Comment` — no decorators, no routing tables, no boilerplate. The fact that it crosses the network is invisible at the call site.
- **Types flow.** Python type hints (primitives, `TypedDict`, `dataclass`, `Literal`, `Union`, `Optional`, `list`, `dict`, `Enum`, `pydantic.BaseModel`) are extracted at build time and emitted as `.d.ts` next to the generated `.js` runtime. TypeScript gives full intellisense in `.svelte` files.
- **Validation where it earns its keep.** Pydantic models on the input side are validated at the wire boundary and produce structured 422 responses with field issues. Stdlib types (TypedDict / primitives) pass through with shallow `isinstance` checks. Pydantic is opt-in, declared as `fymo[pydantic]` extra; apps that don't use it never load it.
- **Two access paths, one mental model.** Functions can be (a) threaded as props from controllers (`getContext()` returns the function reference; SSR serializes it as a marker; client hydrate replaces with fetch stub) or (b) imported directly via `$remote/<module>` in any Svelte component.
- **Identity is automatic.** A `fymo_uid` cookie is issued on first POST. Remote functions read it via `current_uid()`. No auth surface beyond that for v1.
- **TypeScript in `.svelte`.** `<script lang="ts">` works out of the box (already supported by `esbuild-svelte`; we just enable it).

**Non-goals (v1)**

- Schemas as a parallel concept (Valibot/Zod-style DSL). Use type hints + pydantic.
- Automatic form progressive enhancement. JS is required to call remote functions in v1.
- Client-side query caching, deduplication, refresh, single-flight mutations. Each call is one fetch.
- `prerender` / build-time data baking.
- Streaming responses, file uploads.
- Generic types, recursive types, forward refs (emit `unknown` and warn).
- Real auth (login, sessions, RBAC). Cookie identity is a stable token, not a credential.
- Server-side validation hooks (`handleValidationError`).
- Codegen for `getContext()` return shapes (props types from controllers).

## 3. Architecture

```
                    ┌───────────────────────┐
                    │ app/remote/posts.py   │
                    │   def get_post(...)   │
                    │   def create_comment  │  Python — plain functions + type hints
                    │   class NewComment    │  (TypedDict, dataclass, or pydantic)
                    │     (BaseModel)       │
                    └───────────┬───────────┘
                                │ build-time discovery + introspection
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  fymo.remote.codegen                              │
        │   inspect.signature + typing.get_type_hints       │
        │   walk pydantic models, TypedDict, dataclass      │
        │   apply type-mapping table → .d.ts                │
        │   emit fetch wrappers → .js                       │
        └────────────┬───────────────────────┬──────────────┘
                     ▼                       ▼
          ┌─────────────────────┐  ┌─────────────────────┐
          │ dist/client/_remote │  │ dist/client/_remote │
          │  posts.js           │  │  posts.d.ts         │
          └──────────┬──────────┘  └──────────┬──────────┘
                     │                        │
                     │  esbuild $remote/      │  TypeScript picks up
                     │  resolver              │  sibling .d.ts automatically
                     ▼                        ▼
        ┌───────────────────────────────────────────────────┐
        │ app/templates/post/index.svelte                   │
        │   <script lang="ts">                              │
        │     import { create_comment, type Comment }       │
        │       from '$remote/posts';                       │
        │     await create_comment(slug, {name, body});     │
        │   </script>                                       │
        └────────────────────┬──────────────────────────────┘
                             │ POST /__remote/posts/create_comment
                             ▼
              ┌──────────────────────────────────┐
              │ Python WSGI: fymo.remote.router  │
              │   load app.remote.posts          │
              │   match args to signature        │
              │   pydantic.model_validate(...)   │
              │   call function in request scope │
              │   serialize response             │
              └──────────────────────────────────┘
```

**Two coupled deliverables, single PR:**

| Layer | What ships |
|---|---|
| `fymo/remote/` | The framework feature: discovery, introspection, type bridge, codegen, HTTP router, identity helper, request-event context. |
| `examples/blog_app/` | The canonical demo: Python remote module + controllers + Svelte components consuming everything above. Markdown posts seeded into SQLite. Cookie identity. Reactions + comments. |

## 4. Server API: `app/remote/*.py`

Files in `app/remote/` are Python modules whose **top-level callables** become remote functions. Anything else (classes, constants, helpers) is module-private. Convention only — no decorators, no registration step.

### 4.1 Function shape

```python
def fn_name(arg1: T1, arg2: T2, ...) -> R:
    ...
```

- Parameter types must be in the supported set (Section 5). Untyped parameters are an error at codegen time (clear message: "annotate `arg1` of `posts.create_comment`").
- Return type required. `None` is allowed (becomes `void` in TS).
- `*args` / `**kwargs` not supported in v1.
- Default values become optional parameters in TypeScript and optional positional args in the JSON wire format.

### 4.2 Pydantic vs stdlib (hybrid contract)

| Use case | Pick |
|---|---|
| Read-side shapes (DB rows, response data) | `TypedDict` — zero runtime cost, types still flow |
| Write-side inputs (forms, mutations) | `pydantic.BaseModel` with `Field(...)` — validates at wire boundary, structured 422 on failure |
| Single-value input (slug, id, kind) | Just type the parameter (`slug: str`) — no wrapper |
| Tagged unions / enums | `Literal[...]` — emits union of string literals in TS |

Detection rule: at codegen and at request-dispatch time, `issubclass(hint, pydantic.BaseModel)` selects the pydantic adapter; otherwise the stdlib adapter. Both adapters share a single internal interface so the rest of the pipeline doesn't branch.

### 4.3 Identity & request context

```python
from fymo.remote import current_uid, request_event

def create_comment(slug: str, input: NewComment) -> Comment:
    uid = current_uid()  # str; auto-issued on first POST
    ...
```

- `current_uid()` returns the value of the `fymo_uid` cookie. Issued automatically (a 16-byte url-safe token) on the first POST that lacks the cookie; set on the response with `Max-Age=10y; Path=/; SameSite=Lax`.
- `request_event()` returns a small read-only namespace: `event.cookies`, `event.headers`, `event.remote_addr`. v1 doesn't expose write access (no header setting, no redirect).

### 4.4 Errors

Functions can raise:

- `fymo.remote.NotFound(msg)` → 404
- `fymo.remote.Unauthorized(msg)` → 401
- `fymo.remote.Forbidden(msg)` → 403
- `fymo.remote.Conflict(msg)` → 409
- Any other exception → 500 in production; full traceback in dev mode (overlay).

Pydantic `ValidationError` raised at the wire boundary (not by user code) → 422 with `{ issues: e.errors() }`.

## 5. Type bridge: Python → TypeScript

### 5.1 Mapping table

| Python | TypeScript | Notes |
|---|---|---|
| `str` | `string` | |
| `int`, `float`, `Decimal` | `number` | |
| `bool` | `boolean` | |
| `None`, `type(None)` | `null` | |
| `bytes` | `string` | base64-encoded on the wire |
| `list[X]` | `X[]` | |
| `tuple[X, Y, Z]` | `[X, Y, Z]` | fixed length |
| `tuple[X, ...]` | `X[]` | variadic |
| `dict[K, V]` | `Record<K, V>` | K must be `str` |
| `set[X]`, `frozenset[X]` | `X[]` | wire is array |
| `Optional[X]` / `X \| None` | `X \| null` | |
| `Union[X, Y, Z]` | `X \| Y \| Z` | discriminated by shape |
| `Literal["a", "b"]` | `"a" \| "b"` | |
| `TypedDict` | `interface` | |
| `@dataclass` | `interface` | |
| `NamedTuple` | `interface` | |
| `Enum` (str-valued) | `"v1" \| "v2" \| ...` | |
| `Enum` (int-valued) | `0 \| 1 \| ...` | |
| `pydantic.BaseModel` | `interface` | derived from `model_fields` |
| `datetime.datetime`, `date` | `string` | ISO-8601 on the wire |
| `uuid.UUID` | `string` | |
| Generic types `Generic[T]` | `unknown` + warn | v2 |
| Recursive types | `unknown` + warn | v2 |
| Anything else | `unknown` + warn | |

### 5.2 Module emission

For each `app/remote/<name>.py`, emit two siblings under `dist/client/_remote/`:

- `<name>.js` — runtime fetch wrappers, one per top-level function.
- `<name>.d.ts` — typed declarations for every function, plus interfaces / type aliases for every reachable type referenced from those signatures.

Pydantic adapter produces interfaces by walking `model.model_fields` (gets name, annotation, required-ness, default). Stdlib adapter walks `typing.get_type_hints(...)` for TypedDicts/dataclasses/NamedTuples.

Reachable-types walker is recursive but cycle-aware (visited set keyed by `(module, qualname)`). Two type defs from different modules with the same name get module-prefixed: `Posts__Post`, `Comments__Post`. v1 docs that pattern; v2 may add real namespacing.

### 5.3 Generated `.js` shape

```js
// AUTO-GENERATED. Do not edit. Source: app/remote/posts.py
import { __rpc } from '/dist/client/_remote/__runtime.js';

export const get_post        = (slug)         => __rpc('posts/get_post',        [slug]);
export const get_comments    = (slug)         => __rpc('posts/get_comments',    [slug]);
export const create_comment  = (slug, input)  => __rpc('posts/create_comment',  [slug, input]);
export const toggle_reaction = (slug, kind)   => __rpc('posts/toggle_reaction', [slug, kind]);
```

`__runtime.js` exports `__rpc(path, args)` — a thin fetch wrapper documented in Section 7.4.

## 6. HTTP wire protocol

### 6.1 Request

```http
POST /__remote/<module>/<fn> HTTP/1.1
Cookie: fymo_uid=u_4f3a9c
Content-Type: application/json

{"args": [<arg1>, <arg2>, ...]}
```

- One endpoint per remote function. Method is always POST (cacheability not a concern; consistency wins).
- Body is `{args: [...]}`. Even no-arg functions send `{args: []}`.
- The cookie is the only authentication primitive in v1.

### 6.2 Response — success

```http
HTTP/1.1 200 OK
Content-Type: application/json
Set-Cookie: fymo_uid=u_new; Path=/; Max-Age=315360000; SameSite=Lax    ; only if newly issued

{"ok": true, "data": <return value JSON-encoded>}
```

### 6.3 Response — validation error (pydantic input failed)

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/json

{
  "ok": false,
  "error": "validation",
  "issues": [
    {"loc": ["input", "body"], "msg": "String should have at least 1 character", "type": "string_too_short"}
  ]
}
```

### 6.4 Response — domain error (function raised `fymo.remote.NotFound` etc.)

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{"ok": false, "error": "not_found", "message": "post 'unknown-slug' not found"}
```

### 6.5 Response — server error (uncaught)

Production: `500 Internal Server Error` with `{"ok": false, "error": "internal"}` and the original logged.
Dev: 500 with `{"ok": false, "error": "internal", "message": "...", "traceback": "..."}` — the dev error overlay reads it.

## 7. Build pipeline integration

### 7.1 Discovery

`BuildPipeline.discover_remote_modules()` walks `<project>/app/remote/`, importing each module under a sandboxed importer that captures top-level callables and the types they reference. Imports outside `app.remote.*` are allowed; circular imports between remote modules are an error.

### 7.2 Codegen

Per-module: `fymo/remote/codegen.py` writes `<dist>/client/_remote/<name>.js` and `.d.ts`. Plus a single `__runtime.js` shared by all modules.

### 7.3 esbuild plugin: `$remote/<name>`

A custom esbuild plugin (in `fymo/build/js/plugins/remote.mjs`) intercepts imports starting with `$remote/`, resolves them to the corresponding `.js` file under `dist/client/_remote/`. TypeScript's module resolver picks up the sibling `.d.ts` automatically when `<script lang="ts">` is in use.

### 7.4 Client runtime: `__runtime.js`

```js
// dist/client/_remote/__runtime.js
const REMOTE_MARKER = '__fymo_remote';

export async function __rpc(path, args) {
    const res = await fetch('/__remote/' + path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ args }),
    });
    const payload = await res.json().catch(() => ({ ok: false, error: 'invalid_json' }));
    if (payload.ok) return payload.data;
    const err = new Error(payload.message || payload.error);
    err.status = res.status;
    err.error = payload.error;
    err.issues = payload.issues;
    throw err;
}

// Resolves prop markers like {__fymo_remote: "posts/create_comment"}
// emitted by the SSR serializer when a controller threads a remote
// function via getContext().
export function __resolveRemoteProps(props, registry) {
    for (const key in props) {
        const v = props[key];
        if (v && typeof v === 'object' && v[REMOTE_MARKER]) {
            const path = v[REMOTE_MARKER];
            props[key] = (...args) => __rpc(path, args);
        }
    }
    return props;
}
```

The hydration entry calls `__resolveRemoteProps(props, ...)` before `hydrate(Component, { target, props })`.

### 7.5 SSR serialization of callable props

`fymo.core.html.build_html` already emits a JSON island with `props`. Today it crashes if any value is non-JSON-serializable. We add a `default` encoder that, when it sees a callable from `app.remote.*` (detected by `__module__.startswith('app.remote.')`), emits `{__fymo_remote: "<module>/<fn>"}`. Anything else still raises.

## 8. WSGI router

A new top-level WSGI route `POST /__remote/...` short-circuits before the SSR path. Implemented in `fymo/remote/router.py` (~120 lines):

```python
def handle_remote(environ, start_response):
    path = environ['PATH_INFO']  # '/__remote/posts/create_comment'
    parts = path[len('/__remote/'):].split('/')
    if len(parts) != 2:
        return _json(start_response, 400, {"ok": False, "error": "bad_path"})
    module_name, fn_name = parts

    fn, sig, hints = _resolve(module_name, fn_name)
    if fn is None:
        return _json(start_response, 404, {"ok": False, "error": "unknown_function"})

    body = json.loads(environ['wsgi.input'].read(_max_size))
    args = body.get('args', [])

    try:
        validated = _validate_args(args, sig, hints)  # pydantic for BaseModel; isinstance otherwise
    except pydantic.ValidationError as e:
        return _json(start_response, 422, {"ok": False, "error": "validation", "issues": e.errors()})

    uid, set_cookie = _ensure_uid(environ)
    with request_scope(uid=uid, environ=environ):
        try:
            result = fn(*validated)
        except fymo.remote.RemoteError as e:
            return _json(start_response, e.status, {"ok": False, "error": e.code, "message": str(e)}, set_cookie)
        except Exception as e:
            return _internal_error(start_response, e, set_cookie)

    serialized = _serialize_response(result, hints['return'])
    return _json(start_response, 200, {"ok": True, "data": serialized}, set_cookie)
```

Wired into `fymo/core/server.py:FymoApp.__call__` ahead of the static-asset and SSR branches.

## 9. TypeScript in `.svelte`

Enable `<script lang="ts">` via `esbuild-svelte`'s built-in TypeScript handling. Update the build configs in `fymo/build/js/build.mjs` and `fymo/build/js/dev.mjs`:

```js
sveltePlugin({
  preprocess: vitePreprocess(),  // from @sveltejs/vite-plugin-svelte (used standalone)
  compilerOptions: { generate: 'server', dev: false },
})
```

Add `@sveltejs/vite-plugin-svelte` and `typescript` as devDependencies of the framework's `package.json` and the example's. (Type-only; `tsc` is not invoked — esbuild strips types.)

Generate a project-level `tsconfig.json` template in `fymo new` output (and add it to the existing `examples/blog_app/`):

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "paths": {
      "$remote/*": ["./dist/client/_remote/*"]
    }
  },
  "include": ["app/**/*.svelte", "app/**/*.ts"]
}
```

## 10. Blog example: `examples/blog_app/`

### 10.1 Schema (SQLite)

```sql
CREATE TABLE posts (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_html TEXT NOT NULL,    -- pre-rendered at seed time via mistune + pygments
    tags TEXT NOT NULL,            -- comma-separated
    published_at TEXT NOT NULL     -- ISO-8601
);

CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_slug TEXT NOT NULL REFERENCES posts(slug),
    uid TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE reactions (
    post_slug TEXT NOT NULL REFERENCES posts(slug),
    uid TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('clap', 'fire', 'heart', 'mind')),
    PRIMARY KEY (post_slug, uid, kind)
);
```

### 10.2 Seeding

`app/lib/seeder.py` runs at app startup. If `posts` table is empty:

1. Walks `app/posts/*.md`. Each file has YAML front-matter (title, summary, tags, published_at).
2. Renders body via `mistune` with a `pygments`-backed code-block renderer.
3. Inserts a row per post.

Idempotent — re-running with new files inserts new rows; existing slugs are upserted.

### 10.3 Routes

| Route | Controller | Template |
|---|---|---|
| `/` | `index.py` | `templates/index/index.svelte` |
| `/posts/<slug>` | `post.py` | `templates/post/index.svelte` |
| `/tags/<tag>` | `tag.py` | `templates/tag/index.svelte` |

Updated `fymo.yml` resources entry adds `posts/<slug>` and `tags/<tag>` parametric routes (small extension to the existing router; see Section 11).

### 10.4 Remote module: `app/remote/posts.py`

(Verbatim from the design conversation — see the brainstorming transcript section "1. Server".)

### 10.5 Components

- `templates/index/index.svelte` — hero post + recent posts grid. Pure SSR.
- `templates/post/index.svelte` — full post (SSR-rendered HTML body), `ReactionBar` component, `Comments` component.
- `templates/post/ReactionBar.svelte` — uses `import { toggle_reaction } from '$remote/posts'` directly.
- `templates/post/Comments.svelte` — comment form + list. Form uses `create_comment` threaded via `$props()`.
- `templates/_shared/Nav.svelte` — header navigation, theme toggle.

### 10.6 Styling

Dark mode default with light toggle via `prefers-color-scheme` + a button on Nav. Variables on `:root` and `[data-theme="light"]`. Code blocks styled by pygments' `monokai` theme baked in at seed time.

Three sample posts demonstrating different content shapes: a manifesto, a code-heavy technical post, and a comparison piece.

## 11. Router extension for parametric routes

Today `fymo.yml` declares resources as plain strings; the router maps each to `<controller>.<index>`. The blog needs `posts/<slug>` (single-segment param) and `tags/<tag>`. Smallest possible extension:

```yaml
routes:
  resources:
    - posts/<slug>
    - tags/<tag>
    - home
  root: home.index
```

The router's path-matching loop already walks segments; it just needs a small change to capture `<name>` segments into `route_info["params"]`. Controllers receive the captured params as kwargs:

```python
def getContext(slug: str):
    return {...}
```

(This is a small, contained change to `fymo/core/router.py`; ~30 lines.)

## 12. Dependencies

Added to framework `pyproject.toml`:
- `pydantic>=2.5` as **optional** under `[project.optional-dependencies] pydantic = ["pydantic>=2.5"]`. The codegen and adapter detect at import time; absent → only stdlib path is available.

Added to framework `package.json` devDependencies:
- `@sveltejs/vite-plugin-svelte` (used standalone for `vitePreprocess`).
- `typescript` (peer; not invoked, just needed for editor support).

Added to `examples/blog_app/`:
- `mistune>=3` for markdown
- `pygments>=2.17` for code highlighting
- `pydantic>=2.5` (for the input models in `app/remote/posts.py`)

## 13. Errors & dev DX

- Validation error in dev → JSON 422 returned. Client throws Error with `.issues`. Component renders inline form errors (per existing `<form>` patterns).
- Function not found → 404, dev error overlay shows the request path and lists known remote functions.
- Type unsupported during codegen → build fails with clear message: `"app/remote/posts.py: cannot map type 'MyCustomClass' for return of 'create_post'. Use TypedDict, dataclass, or pydantic BaseModel."`
- Stack traces in dev overlay; prod returns generic 500.

## 14. Rollout (six phases)

| Phase | Output |
|---|---|
| A. TypeScript in `.svelte` | `<script lang="ts">` works; existing build still green; tests pass. |
| B. `app/remote/*` discovery + introspection | Python lib that, given a project root, returns `{module: {fn: signature_with_hints}}`. Unit-tested. |
| C. Type-mapping codegen | Given a discovery result, emits `.js` + `.d.ts` in `dist/client/_remote/`. Unit-tested with golden files. |
| D. WSGI `/__remote/<m>/<fn>` | Routes, validates, dispatches, serializes. Identity cookie. Tests cover happy path + 404 + 422 + domain errors. |
| E. esbuild `$remote/` resolver + SSR callable serialization | `import from '$remote/...'` works; `getContext()` can return callable references and they hydrate. |
| F. Blog example | All of the above wired up; ships as `examples/blog_app/`. |

Each phase is a separate PR-shaped commit. A and B–C–D can be developed in parallel since they don't depend on each other.

## 15. Open questions / risks

1. **`vitePreprocess` standalone usage** — using vite-plugin-svelte's preprocessor outside Vite is supported but undocumented. If it breaks, fallback is `svelte-preprocess` (older but stable).
2. **Type-mapping for unions of literals + objects** (e.g., `Literal["error"] | ErrorBody`) — discriminated unions are doable but increase complexity. v1 emits the union as TS but doesn't enforce discriminator at runtime.
3. **Multiple `app/remote/*` modules sharing type names** — handled by module prefixing in v1. Document the rule.
4. **Cookie security** — `fymo_uid` is HttpOnly + Secure (when over HTTPS) + SameSite=Lax. Document that it's an identity token, not a credential.
5. **Maximum request body size** — default 1MB; configurable. Reject larger with 413.
6. **CSRF** — `SameSite=Lax` cookies + same-origin fetch by default mitigate this for v1. Document the threat model; v2 may add a CSRF token for stricter setups.
7. **Module hot-reload in `fymo dev`** — when `app/remote/*.py` changes, the WSGI router's import cache must be invalidated. Use `importlib.reload` triggered by the same SSE channel that triggers browser reload.

## 16. Out of scope (explicit non-features)

- Schema DSL parallel to type hints.
- Form progressive enhancement (no-JS forms).
- Client-side caching, dedup, refresh, single-flight.
- Build-time prerender.
- Real auth (login, sessions, RBAC, token refresh).
- WebSockets / SSE for live data.
- File uploads.
- Streaming responses.
- Generic & recursive types in codegen.
- Controller-level prop type generation.

## 17. Acceptance

The feature is "done" when, with the framework freshly installed:

```bash
cd examples/blog_app
pip install fymo[pydantic]
npm install
fymo build
fymo serve
```

…produces a working blog at `http://localhost:8000` where:

- The home page lists three seeded posts.
- Clicking a post navigates to a detail page rendered with full SSR (HTML inspection shows the post body in the response).
- Clicking a reaction button increments its counter and persists across reload (DB write + new SSR data).
- Submitting an invalid comment (empty body) shows an inline error from the pydantic 422.
- Submitting a valid comment appends it to the list optimistically and persists to the DB.
- Opening DevTools shows a single `POST /__remote/posts/create_comment` per submission.
- Opening `app/templates/post/index.svelte` in an editor with TypeScript shows full intellisense for the imported remote functions.
