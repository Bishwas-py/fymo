---
title: How Fymo's build pipeline works
summary: A walk through the esbuild + Node sidecar + manifest architecture
tags: architecture,build
published_at: 2026-04-28T11:00:00Z
---

# How Fymo's build pipeline works

When you run `fymo build`, here's what happens, in order.

## 1. Discovery

The Python orchestrator walks `app/templates/` looking for `<route>/index.svelte` files. Each match becomes a route entry — `app/templates/posts/show.svelte` → route `posts`.

It also walks `app/remote/` and introspects every top-level callable: pulls the `inspect.signature`, resolves type hints with `typing.get_type_hints`, and walks every referenced type.

## 2. Server pass

esbuild bundles each route as a server module:

```js
await esbuild.build({
    entryPoints: { posts: 'app/templates/posts/show.svelte', ... },
    outdir: 'dist/ssr',
    format: 'esm',
    platform: 'node',
    bundle: true,
    plugins: [sveltePlugin({ compilerOptions: { generate: 'server' } })],
});
```

Each `dist/ssr/<route>.mjs` exports a Svelte component — the sidecar imports it at runtime.

## 3. Client pass

Same input, different config:

- `platform: 'browser'`
- `splitting: true` (this is the magic — date-fns imported by both `posts` and `tags` ends up in one shared chunk)
- `entryNames: '[name].[hash]'` for long-cache safety

## 4. Remote codegen

For each `app/remote/<name>.py`, emit a sibling `.js` (fetch wrappers) and `.d.ts` (TypeScript declarations) under `dist/client/_remote/`.

## 5. Manifest

Write `dist/manifest.json` mapping each route to its hashed JS, CSS, and shared chunk preload list.

## 6. Sidecar

Copy `sidecar.mjs` to `dist/`. The Python server spawns it once per `fymo serve`; it imports SSR modules lazily and answers stdio JSON requests.
