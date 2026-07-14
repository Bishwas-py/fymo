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
| `app/remote` | Python | Functions callable from the browser via the generated `$remote` client. Public, type-annotated top-level functions are exposed by default; mark with `@remote` (`fymo.remote.remote`) to opt into `remote.explicit_optin` mode. |
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
