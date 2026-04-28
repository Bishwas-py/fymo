<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
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
    create_comment: (slug: string, input: { name: string; body: string }) => Promise<Comment>;
    toggle_reaction: (slug: string, kind: 'clap' | 'fire' | 'heart' | 'mind') => Promise<ReactionCounts>;
  } = $props();
</script>

<Nav />

<article>
  <h1>{post.title}</h1>
  <p class="meta">{new Date(post.published_at).toDateString()} · {post.tags}</p>
  <div class="body">{@html post.content_html}</div>
</article>

<ReactionBar slug={post.slug} initial={initial_reactions} {toggle_reaction} />
<Comments slug={post.slug} initial={initial_comments} {create_comment} />

<style>
  article h1 { font-size: 2.4rem; margin: 0 0 0.5rem; }
  .meta { color: var(--muted); font-size: 0.9rem; margin: 0 0 2rem; }
  .body :global(p) { font-size: 1.05rem; line-height: 1.7; color: var(--fg); }
  .body :global(pre) {
    background: var(--code-bg); padding: 1rem; border-radius: 0.4rem;
    overflow-x: auto; font-size: 0.9rem;
    border: 1px solid var(--rule);
  }
  .body :global(code) {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
  }
  .body :global(p code) {
    background: var(--code-bg); padding: 0.1rem 0.4rem; border-radius: 0.25rem; font-size: 0.92em;
  }
  .body :global(h2) { font-size: 1.5rem; margin: 2rem 0 0.5rem; }
</style>
