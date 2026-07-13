<script lang="ts">
  import Comments from './Comments.svelte';
  import ReactionBar from './ReactionBar.svelte';
  import type { Post, Comment, ReactionCounts } from '$remote/posts';

  let {
    post,
    initial_comments,
    initial_reactions,
    create_comment,
    toggle_reaction,
  }: {
    post: Post;
    initial_comments: Comment[];
    initial_reactions: ReactionCounts;
    create_comment: (slug: string, input: { body: string }) => Promise<Comment>;
    toggle_reaction: (slug: string, kind: 'clap' | 'fire' | 'heart' | 'mind') => Promise<ReactionCounts>;
  } = $props();
</script>

<article>
  <header class="post-head">
    <p class="dateline">
      <time>{new Date(post.published_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}</time>
      <span class="tags">{post.tags}</span>
    </p>
    <h1>{post.title}</h1>
  </header>
  <div class="body">{@html post.content_html}</div>
</article>

<ReactionBar slug={post.slug} initial={initial_reactions} {toggle_reaction} />
<Comments slug={post.slug} initial={initial_comments} {create_comment} />

<style>
  .post-head { margin-bottom: 2.5rem; }
  .dateline {
    display: flex; gap: 1rem; align-items: center;
    font-family: var(--font-mono); font-size: 0.78rem; color: var(--muted); margin: 0 0 1rem;
  }
  .dateline .tags { color: var(--accent); }
  article h1 { font-size: clamp(2.1rem, 5.5vw, 3rem); font-weight: 700; margin: 0; }

  /* ---- Prose ---- */
  .body { font-size: 1.09rem; line-height: 1.78; }
  .body :global(p) { margin: 0 0 1.4rem; color: var(--fg); }
  .body :global(h2) {
    font-family: var(--font-display); font-size: 1.6rem; font-weight: 600;
    margin: 2.8rem 0 0.9rem; letter-spacing: -0.02em;
  }
  .body :global(h3) { font-family: var(--font-display); font-size: 1.25rem; margin: 2rem 0 0.6rem; }
  .body :global(a) { text-decoration: underline; text-decoration-color: color-mix(in srgb, var(--accent) 45%, transparent); text-underline-offset: 3px; }
  .body :global(a:hover) { text-decoration-color: var(--accent); }
  .body :global(strong) { font-weight: 650; }
  .body :global(ul), .body :global(ol) { margin: 0 0 1.4rem; padding-left: 1.3rem; }
  .body :global(li) { margin: 0.35rem 0; }
  .body :global(blockquote) {
    margin: 1.8rem 0; padding: 0.4rem 0 0.4rem 1.3rem;
    border-left: 3px solid var(--accent); color: var(--muted); font-style: italic;
  }
  .body :global(pre) {
    background: var(--code-bg); padding: 1.15rem 1.25rem; border-radius: 12px;
    overflow-x: auto; font-size: 0.88rem; line-height: 1.6;
    border: 1px solid var(--rule); margin: 1.6rem 0;
  }
  .body :global(code) { font-family: var(--font-mono); }
  .body :global(pre code) { font-size: 0.88rem; }
  .body :global(p code), .body :global(li code) {
    background: var(--surface-2); padding: 0.12rem 0.42rem; border-radius: 6px;
    font-size: 0.88em; border: 1px solid var(--rule);
  }
  .body :global(hr) { border: none; border-top: 1px solid var(--rule); margin: 2.5rem 0; }
</style>
