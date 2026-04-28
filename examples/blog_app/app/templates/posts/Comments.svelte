<script lang="ts">
  import type { Comment } from '$remote/posts';

  let {
    slug,
    initial,
    create_comment,
  }: {
    slug: string;
    initial: Comment[];
    create_comment: (slug: string, input: { name: string; body: string }) => Promise<Comment>;
  } = $props();

  let comments = $state([...initial]);
  let name = $state('');
  let body = $state('');
  let error: string | null = $state.raw(null);
  let pending = $state(false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (pending) return;
    pending = true;
    error = null;
    try {
      const c = await create_comment(slug, { name, body });
      comments = [c, ...comments];
      body = '';
    } catch (err: any) {
      error = err.issues?.[0]?.msg ?? err.message ?? 'Submission failed';
    } finally {
      pending = false;
    }
  }
</script>

<section class="comments">
  <h2>{comments.length} {comments.length === 1 ? 'comment' : 'comments'}</h2>

  <form onsubmit={submit}>
    <input bind:value={name} placeholder="Your name" required maxlength="60" />
    <textarea bind:value={body} placeholder="Leave a comment" required maxlength="1000" rows="3"></textarea>
    {#if error}<p class="err">{error}</p>{/if}
    <button disabled={pending}>{pending ? 'Posting…' : 'Post comment'}</button>
  </form>

  <ul>
    {#each comments as c (c.id)}
      <li>
        <header>
          <strong>{c.name}</strong>
          <time>{new Date(c.created_at).toLocaleString()}</time>
        </header>
        <p>{c.body}</p>
      </li>
    {/each}
  </ul>
</section>

<style>
  h2 { font-size: 1.2rem; margin: 2rem 0 1rem; }
  form {
    display: flex; flex-direction: column; gap: 0.75rem;
    margin-bottom: 2rem;
    padding: 1.25rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 0.5rem;
  }
  input, textarea {
    background: var(--bg);
    color: var(--fg);
    border: 1px solid var(--rule);
    border-radius: 0.3rem;
    padding: 0.6rem 0.75rem;
    font: inherit;
    resize: vertical;
  }
  input:focus, textarea:focus { outline: none; border-color: var(--accent); }
  button {
    align-self: flex-start;
    background: var(--accent); color: white;
    border: none; border-radius: 0.3rem;
    padding: 0.5rem 1rem; cursor: pointer;
    font: inherit; font-weight: 600;
  }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  .err { color: #ff7b72; font-size: 0.9rem; margin: 0; }

  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1rem; }
  li {
    border-left: 3px solid var(--rule);
    padding: 0.25rem 0 0.25rem 1rem;
  }
  li header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.3rem; }
  li time { color: var(--muted); font-size: 0.85rem; }
  li p { margin: 0; line-height: 1.5; }
</style>
