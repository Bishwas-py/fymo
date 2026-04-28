<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
  import type { PostSummary } from '$remote/posts';

  let { tag, posts }: { tag: string; posts: PostSummary[] } = $props();
</script>

<Nav />
<h1>Posts tagged <span class="tag">{tag}</span></h1>
<ul>
  {#each posts as p}
    <li><a href="/posts/{p.slug}">{p.title}</a></li>
  {/each}
</ul>

<style>
  .tag { color: var(--accent); }
  ul { list-style: none; padding: 0; }
  li { border-bottom: 1px solid var(--rule); padding: 1rem 0; }
</style>
