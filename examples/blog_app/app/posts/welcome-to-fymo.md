---
title: Welcome to Fymo
summary: A Python framework for SSR Svelte apps without the SvelteKit weight
tags: announcement,fymo
published_at: 2026-04-28T10:00:00Z
---

# Welcome to Fymo

Fymo is what you'd build if you wanted SvelteKit's developer ergonomics but on a Python backend, without dragging Node into your data layer.

## Why?

Most full-stack JS frameworks force the entire stack to live in one runtime. That's elegant when your team is JS-only, but punishes Python shops who already have working Django, FastAPI, or Flask code and a database their ORM understands.

Fymo lets you keep Python on the server and use Svelte 5 on the client, with a build-time pipeline that emits cacheable, hashed assets and a Node sidecar that handles per-request SSR.

## What's inside

- **Build-time esbuild pipeline** — `fymo build` produces `dist/` with hashed JS, CSS, and a Node SSR sidecar.
- **Persistent Node sidecar** — Python WSGI talks to a long-lived `node` over stdio. Microsecond per-request SSR.
- **Cross-route shared chunks** — `date-fns` imported by every page bundles once and ships once.
- **Remote functions** — write Python in `app/remote/posts.py`, call from Svelte as if local.

```python
def get_posts() -> list[Post]:
    return db.fetchall("SELECT * FROM posts")
```

```svelte
<script lang="ts">
  import { get_posts } from '$remote/posts';
  let posts = await get_posts();
</script>
```

That's it.
