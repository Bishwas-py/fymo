# Journal Entry 004: Remote Functions - Python Functions You Can Call From Svelte

**Date**: April 28, 2026
**Focus**: `app/remote/*.py` + typed `$remote` client, plus a blog example to prove it
**Status**: ✅ Shipped

## The Gap

Fymo was one-way. Controllers compute `getContext()`, props get SSR'd into
the page, the client hydrates, and then... nothing. There was no defined way
for the client to send anything back. Every app would have to invent its own
fetch + endpoint glue, which means every app reinvents JSON serialization,
validation, error handling, cookie plumbing, and path conventions. That's
the kind of boilerplate a framework exists to delete.

## The Feature

Write a plain Python function, call it from Svelte like it's local:

```python
# app/remote/posts.py
def create_comment(slug: str, input: NewComment) -> Comment:
    ...
```

```svelte
<script lang="ts">
  import { create_comment, type Comment } from '$remote/posts';
  await create_comment(slug, { name, body });
</script>
```

No decorators, no routing tables. The fact that the call crosses the
network is invisible at the call site.

## How Types Flow

This was the part I cared about most. Build-time introspection
(`inspect.signature` + `typing.get_type_hints`) walks the function
signatures and emits two files per module into `dist/client/_remote/`:

- `posts.js` - fetch wrappers
- `posts.d.ts` - TypeScript declarations

TypedDict, dataclass, Literal, Union, Optional, list, dict, Enum, and
pydantic models all map to proper TS types, so `.svelte` files get full
intellisense. An esbuild resolver maps `$remote/posts` to the generated
runtime.

Validation is tiered on purpose. Pydantic models get validated at the wire
boundary and produce structured 422 responses with per-field issues. Stdlib
types pass through with shallow isinstance checks. And pydantic itself is an
optional extra (`fymo[pydantic]`), so apps that don't want it never load it.

## Two Access Paths, One Mental Model

1. **Threaded as props**: a controller returns the function reference from
   `getContext()`; SSR serializes it as a marker; hydration replaces the
   marker with a fetch stub. The component just receives a callable prop.
2. **Direct import**: `import { fn } from '$remote/<module>'` anywhere.

Identity came along for free: a `fymo_uid` cookie is issued on first POST
and remote functions read it via `current_uid()`. Not auth, just a stable
anonymous identity. Real auth came later (see entry 006).

## The Blog Example

Shipped a full blog example in the same PR, on purpose. It consumes every
part of the new surface: typed reads, validated writes, props-threaded
callables, direct imports, cookie identity, TypeScript components. If the
demo can't be written cleanly, the API isn't done. Writing it caught several
rough edges before anyone else could.

## What I Said No To

Zod-style schema DSLs (type hints are the schema), automatic form
progressive enhancement, client-side query caching, streaming, file uploads,
generic/recursive types (they emit `unknown` with a warning). All v2
material. The v1 bar was: one obvious way to define a function, one obvious
way to call it, types all the way through.

---

*End of Journal Entry 004*
