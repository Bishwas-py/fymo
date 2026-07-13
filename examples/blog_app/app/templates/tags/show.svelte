<script lang="ts">
  import type { PostSummary } from '$remote/posts';

  let { tag, posts }: { tag: string; posts: PostSummary[] } = $props();
</script>

<header class="head">
  <p class="kicker">Tag</p>
  <h1>#{tag}</h1>
  <p class="count">{posts.length} {posts.length === 1 ? 'post' : 'posts'}</p>
</header>

<ul>
  {#each posts as p}
    <li>
      <a href="/posts/{p.slug}">
        <span class="title">{p.title}</span>
        <span class="arrow">→</span>
      </a>
    </li>
  {/each}
</ul>

<style>
  .head { margin-bottom: 2.5rem; }
  .kicker {
    font-family: var(--font-mono); font-size: 0.72rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--muted); margin: 0;
  }
  .head h1 { font-size: clamp(2.2rem, 6vw, 3rem); font-weight: 700; margin: 0.6rem 0 0.4rem; color: var(--accent); }
  .count { font-family: var(--font-mono); font-size: 0.8rem; color: var(--muted); margin: 0; }

  ul { list-style: none; padding: 0; margin: 0; }
  li { border-top: 1px solid var(--rule); }
  li:last-child { border-bottom: 1px solid var(--rule); }
  a {
    display: flex; justify-content: space-between; align-items: center;
    padding: 1.2rem 0.4rem; color: var(--fg);
    transition: background 0.15s ease, padding-left 0.15s ease;
  }
  a:hover { background: var(--surface); padding-left: 1rem; }
  .title { font-family: var(--font-display); font-weight: 600; font-size: 1.15rem; }
  .arrow { color: var(--muted); transition: transform 0.15s ease, color 0.15s ease; }
  a:hover .arrow { color: var(--accent); transform: translateX(4px); }
</style>
