<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
  import type { PostSummary } from '$remote/posts';

  let { hero, posts }: { hero: PostSummary | null; posts: PostSummary[] } = $props();

  const fmt = (d: string) =>
    new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
</script>

<Nav />

<header class="intro">
  <p class="kicker">Python on the server · Svelte on the client</p>
  <h1>Field notes from building <span class="hl">fymo</span>.</h1>
  <p class="dek">
    SvelteKit ergonomics on a Python backend — SSR, remote functions, and a
    build that ships bytes, not frameworks.
  </p>
</header>

{#if hero}
  <a class="hero" href="/posts/{hero.slug}">
    <p class="kicker accent">Featured</p>
    <h2>{hero.title}</h2>
    <p class="summary">{hero.summary}</p>
    <p class="meta">
      <time>{fmt(hero.published_at)}</time>
      <span class="tags">{hero.tags}</span>
      <span class="go">Read →</span>
    </p>
  </a>
{/if}

<section class="feed">
  <p class="kicker section-label">Latest writing</p>
  <ul>
    {#each posts as p}
      <li>
        <a href="/posts/{p.slug}">
          <time>{fmt(p.published_at)}</time>
          <span class="body">
            <span class="title">{p.title}</span>
            <span class="summary">{p.summary}</span>
          </span>
          <span class="arrow">→</span>
        </a>
      </li>
    {/each}
  </ul>
</section>

<style>
  .kicker {
    font-family: var(--font-mono);
    font-size: 0.72rem; letter-spacing: 0.16em; text-transform: uppercase;
    color: var(--muted); margin: 0;
  }
  .kicker.accent { color: var(--accent); }

  .intro { margin-bottom: 3.5rem; }
  .intro h1 { font-size: clamp(2.4rem, 6vw, 3.4rem); font-weight: 700; margin: 0.9rem 0 1rem; }
  .intro .hl {
    color: var(--accent);
    background: linear-gradient(transparent 68%, color-mix(in srgb, var(--accent) 22%, transparent) 0);
  }
  .intro .dek {
    color: var(--muted); font-size: 1.12rem; line-height: 1.6; max-width: 34rem; margin: 0;
  }

  .hero {
    display: block; color: var(--fg);
    padding: 1.8rem; margin-bottom: 4rem;
    background: var(--surface);
    border: 1px solid var(--rule);
    border-radius: 16px;
    transition: border-color 0.2s ease, transform 0.2s ease;
  }
  .hero:hover { border-color: color-mix(in srgb, var(--accent) 55%, var(--rule)); transform: translateY(-2px); }
  .hero h2 { font-size: 1.9rem; font-weight: 700; margin: 0.7rem 0 0.7rem; }
  .hero .summary { color: var(--muted); font-size: 1.05rem; margin: 0 0 1.3rem; }
  .hero .meta {
    display: flex; align-items: center; gap: 1rem;
    font-family: var(--font-mono); font-size: 0.78rem; color: var(--muted); margin: 0;
  }
  .hero .tags { color: var(--muted); }
  .hero .go { margin-left: auto; color: var(--accent); font-weight: 500; }

  .section-label { margin-bottom: 1.2rem; }
  .feed ul { list-style: none; padding: 0; margin: 0; }
  .feed li { border-top: 1px solid var(--rule); }
  .feed li:last-child { border-bottom: 1px solid var(--rule); }
  .feed a {
    display: grid;
    grid-template-columns: 6.5rem 1fr auto;
    gap: 1.25rem; align-items: baseline;
    padding: 1.4rem 0.4rem; color: var(--fg);
    transition: background 0.15s ease, padding-left 0.15s ease;
  }
  .feed a:hover { background: var(--surface); padding-left: 1rem; }
  .feed time { font-family: var(--font-mono); font-size: 0.76rem; color: var(--muted); }
  .feed .body { display: flex; flex-direction: column; gap: 0.25rem; }
  .feed .title { font-family: var(--font-display); font-weight: 600; font-size: 1.15rem; }
  .feed .summary { color: var(--muted); font-size: 0.92rem; line-height: 1.5; }
  .feed .arrow { color: var(--muted); transition: transform 0.15s ease, color 0.15s ease; }
  .feed a:hover .arrow { color: var(--accent); transform: translateX(4px); }

  @media (max-width: 34rem) {
    .feed a { grid-template-columns: 1fr auto; }
    .feed time { grid-column: 1 / -1; }
  }
</style>
