---
title: Why Svelte 5 + Python is a great combo
summary: Reactive UI without the JS-everywhere tax
tags: opinion,svelte,python
published_at: 2026-04-28T12:00:00Z
---

# Why Svelte 5 + Python is a great combo

The last decade of full-stack frameworks has, with very few exceptions, said: pick a runtime, run everything in it. Next.js puts your data layer in JS. Django insists on Jinja templates that age like milk. Phoenix LiveView is brilliant but ties you to BEAM.

Svelte 5 changed the calculus.

## Runes are reactive without ceremony

```svelte
<script>
  let count = $state(0);
  let doubled = $derived(count * 2);
</script>

<button onclick={() => count++}>{doubled}</button>
```

That's the entire mental model. No `useState`, no `useMemo`, no dependency arrays. Just declare what's reactive and let the compiler track it.

## The runtime is tiny

A typical Svelte 5 page bundle is 5–15 KB after gzip. React + RSC clocks in at 80 KB+. That difference is real on slow phones and contested networks.

## Python is *fine* for the data layer

Your team already speaks SQL. `pandas` exists. `pydantic` is industrial-strength validation. ORMs are excellent. There's no reason to translate your data layer into TypeScript just so you can render it in JSX.

Fymo splits the difference: Python where it shines, Svelte where it shines, a thin wire format between them.
