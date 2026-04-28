<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
  import type { PostSummary } from '$remote/posts';

  let { hero, posts }: { hero: PostSummary | null; posts: PostSummary[] } = $props();
</script>

<Nav />

{#if hero}
  <article class="hero">
    <a href="/posts/{hero.slug}">
      <h1>{hero.title}</h1>
      <p class="summary">{hero.summary}</p>
      <p class="meta">{new Date(hero.published_at).toDateString()} · {hero.tags}</p>
    </a>
  </article>
{/if}

<section class="grid">
  {#each posts as p}
    <a class="card" href="/posts/{p.slug}">
      <h2>{p.title}</h2>
      <p>{p.summary}</p>
      <p class="meta">{p.tags}</p>
    </a>
  {/each}
</section>

<style>
  .hero {
    border: 1px solid var(--rule);
    border-radius: 0.6rem;
    padding: 2rem;
    margin-bottom: 3rem;
    background: var(--card);
  }
  .hero a { color: var(--fg); }
  .hero h1 { font-size: 2.2rem; margin: 0 0 0.5rem; }
  .summary { color: var(--muted); font-size: 1.1rem; line-height: 1.6; margin: 0 0 1rem; }
  .meta { color: var(--muted); font-size: 0.85rem; margin: 0; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1rem;
  }
  .card {
    border: 1px solid var(--rule);
    border-radius: 0.5rem;
    padding: 1.25rem;
    color: var(--fg);
    transition: background 0.15s;
  }
  .card:hover { background: var(--card); }
  .card h2 { font-size: 1.1rem; margin: 0 0 0.5rem; }
  .card p { color: var(--muted); margin: 0 0 0.5rem; font-size: 0.92rem; }
</style>
