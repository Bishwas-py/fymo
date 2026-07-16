# The `app/` directory contract

This is a short, factual reference for what each `app/` subdirectory is for.
It's a seed doc, not the full docs site (see issue #14 for that). When in
doubt, `fymo/build/hygiene.py` and `fymo/core/app_discovery.py` are the
source of truth; this page just writes down what they already enforce (or,
for `app/lib` and `app/support`, what they warn about) so it isn't only
tribal knowledge.

| Directory | Language | Purpose |
|---|---|---|
| `app/controllers` | Python | Page controllers, one module per route, exposing `getContext()`/`getDoc()` to the matching template. |
| `app/templates` | Svelte / TS | The page components the router renders, one file per route (plus `_layout.svelte` files and `_global.css`). |
| `app/components` | Svelte / TS | Reusable UI components shared across templates. |
| `app/remote` | Python | Functions callable from the browser via the generated `$remote` client. Public, type-annotated top-level functions are exposed by default; mark with `@remote` (`fymo.remote.remote`) to opt into `remote.mode: strict`. |
| `app/jobs` | Python | Background task registry, submitted through a `JobProvider`. Every non-underscore top-level function becomes a submittable task; mark task entry points with `@task` (`fymo.jobs.task`) to say so explicitly (see below). |
| `app/broadcasts` | Python | SSE channel definitions, discovered the same way as `app/jobs`. |
| `app/lib` | TypeScript / Svelte | The `$lib/*` alias target (see `tsconfig.json`). TypeScript-only, there is no Python here, because nothing under `app/lib` ever runs server-side. |
| `app/support` | Python | Shared server-side utilities that don't fit any of the above: a database connection helper, auth env config, media path helpers, and similar cross-cutting code imported by controllers/remote/jobs modules. |

## `app/controllers` and `app/templates`/`app/components` are hard build errors

`fymo build` and `fymo dev` both run `check_directory_hygiene()`
(`fymo/build/hygiene.py`) before anything else: a `.svelte` file under
`app/controllers/`, or a `.py` file under `app/templates/`/`app/components/`,
fails the build. Nothing silently ignores the misplaced file: Python never
imports a stray `.svelte`, and esbuild never bundles a stray `.py`, so
without this check the file would just do nothing instead of erroring where
a developer would notice.

## `app/lib` is a warning, not an error

A `.py` file under `app/lib/` is almost always a sign the code belongs in
`app/support/` instead. `app/lib` is the `$lib/*` alias target for
TypeScript/Svelte imports, and Python there never gets bundled or run. Unlike
the checks above, this is a build-time **warning**, not a hard failure: it
doesn't block `fymo build` or `fymo dev`, it just prints a suggestion to move
the file to `app/support/`.

## `@task` and `app/jobs`

`app/jobs/*.py` files are meant to be thin task registries: a handful of
submittable entry points, not a place implementation piles up. Because every
non-underscore top-level function in `app/jobs/*.py` becomes a submittable
task, helpers that shouldn't be submittable have to be underscore-prefixed
to stay private, which is easy to forget, and easy for a file to grow past
the point where "thin registry" is still true.

`@task` (`from fymo.jobs import task`) marks a function as an intentional
task entry point. It doesn't change what gets discovered: an undecorated
top-level function is still registered exactly as before, for backward
compatibility, but an undecorated one now also logs a one-line deprecation
warning suggesting `@task` be added. Real implementation that a task calls
into belongs in `app/support/`, not underscore-prefixed helpers living next
to the task in the same module.

## `$route`: reactive current-route state

`location.pathname` read inside `$effect` never re-runs after a soft
navigation — it's a plain DOM property, not something Svelte's reactivity
tracks. `$route` is fymo's answer: a `svelte/store` writable, resolved the
same way `$remote/<name>` and `$broadcast/<name>` are (a virtual import
`fymo/build/js/plugins/router.mjs` resolves at build time), carrying the
current path, query string, and any matched `:id`-style route params:

```svelte
<script>
  import { route } from '$route';
</script>

<p>Current: {$route.pathname}, id={$route.params.id}</p>
```

`route.pathname` / `route.search` come from `window.location` and update
on every soft nav; `route.params` comes from the same server-side
`Router.match()` result a controller's `getContext(params)` already
receives — it's a guaranteed field, not something a controller has to echo
back into props for the client to see. Seeded before `hydrate()` and
updated by the soft-nav router, not by the SSR render pass: reads inside
`$effect`/event handlers are correct from first paint on, but a `$route`
read in top-level template markup during the very first render may
briefly differ from what the server rendered, the same as any other value
that legitimately differs between server and client.

## Paginated remote functions

Nothing stops a remote function from returning every row, and at demo row
counts that works, which is exactly the problem: `list_x()` returning the
whole table is the path of least resistance and gives no signal in dev that
it stops working later. The convention for anything list-shaped that can
grow is cursor pagination:

```python
from typing import TypedDict
from fymo.remote import remote, decode_cursor, paginate


class PostsPage(TypedDict):
    items: list[PostSummary]
    next_cursor: str | None    # opaque; null means "no more pages"


@remote
def list_posts(cursor: str | None = None, limit: int = 20) -> PostsPage:
    limit = max(1, min(limit, 50))
    fields = "slug, title, summary, tags, published_at"
    if cursor:
        published_at, slug = decode_cursor(cursor, expect=2)
        rows = get_db().fetchall(
            f"SELECT {fields} FROM posts WHERE (published_at, slug) < (?, ?) "
            "ORDER BY published_at DESC, slug DESC LIMIT ?",
            [published_at, slug, limit + 1],
        )
    else:
        rows = get_db().fetchall(
            f"SELECT {fields} FROM posts ORDER BY published_at DESC, slug DESC LIMIT ?",
            [limit + 1],
        )
    return paginate(rows, limit, key=lambda p: (p["published_at"], p["slug"]))
```

This is copied from `examples/blog_app/app/remote/posts.py`, which
demonstrates it end to end (the home page SSRs the first page and a "More
posts" button fetches the rest through the `$remote` client).

The pieces, all from `fymo.remote`:

- **`encode_cursor(*values)` / `decode_cursor(cursor, expect=n)`** — an
  opaque cursor is just base64url-encoded JSON of the last-seen sort-key
  value(s). `decode_cursor` raises a `RemoteError` that the router turns
  into a 400 `bad_cursor` envelope on any garbage input (bad base64,
  non-JSON, wrong arity, nested values, ints beyond the JS safe-integer
  range), so a tampered cursor can never become a 500. One thing it
  cannot detect: a *well-formed* cursor pasted from a different paginated
  function with the same arity decodes fine and just yields a wrong or
  empty page — cursors are opaque, not authenticated.
- **The fetch-one-extra idiom** — query `LIMIT limit + 1`. Getting
  `limit + 1` rows back proves there's a next page without a second
  `COUNT(*)` query; `paginate(rows, limit, key=...)` drops the extra row
  and encodes the last *kept* row's sort key(s) as `next_cursor`, or `None`
  when the extra row didn't come back.
- **A unique sort key** — the cursor must identify an exact position, so
  sort by something unique. A timestamp alone usually isn't; the example
  uses `(published_at, slug)` with SQLite's row-value comparison. A single
  auto-increment `id` works too: `WHERE id < ? ORDER BY id DESC`, with
  `key=lambda r: r["id"]`.

Why cursor instead of `offset`? `OFFSET n` scans and discards `n` rows on
every page, and a row inserted between two requests shifts every subsequent
page (items repeat or vanish). A cursor is a WHERE clause on an indexed
column: constant cost per page, stable under concurrent writes, and it
devalue-round-trips as a plain string.

Declare the page shape as a plain per-module TypedDict (`PostsPage`), not a
generic `Page[T]`. Codegen (`fymo/remote/typemap.py`) maps a subscripted
generic TypedDict to `unknown` — a plain TypedDict comes out as a real
interface:

```ts
export interface PostsPage {
  items: PostSummary[];
  next_cursor: string | null;
}
export function list_posts(cursor?: string | null, limit?: number): Promise<PostsPage>;
```

On the client, page one is a call with no cursor; every next page feeds the
previous `next_cursor` back in until it comes back `null`:

```svelte
<script lang="ts">
  let feed = $state<PostSummary[]>([]);
  let cursor: string | null = $state(null);

  async function loadMore() {
    const page = await list_posts(cursor, 10);
    feed = [...feed, ...page.items];
    cursor = page.next_cursor;   // null => hide the button
  }
</script>
```

Omitted arguments use the Python-side defaults: the generated client sends
`undefined` for a skipped trailing argument and the dispatcher substitutes
the parameter default, so `list_posts()` means `cursor=None, limit=20`.
