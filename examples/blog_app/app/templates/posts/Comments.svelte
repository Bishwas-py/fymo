<script lang="ts">
  import { onMount } from 'svelte';
  import type { Comment } from '$remote/posts';
  import { user, ready, ensureLoaded } from '$lib/auth';
  import AuthForm from '$components/AuthForm.svelte';

  let {
    slug,
    initial,
    create_comment,
  }: {
    slug: string;
    initial: Comment[];
    create_comment: (slug: string, input: { body: string }) => Promise<Comment>;
  } = $props();

  let comments = $state([...initial]);
  let body = $state('');
  let error: string | null = $state.raw(null);
  let pending = $state(false);

  onMount(ensureLoaded);

  const handle = $derived($user ? $user.email.split('@')[0] : '');

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (pending) return;
    pending = true;
    error = null;
    try {
      const c = await create_comment(slug, { body });
      comments = [c, ...comments];
      body = '';
    } catch (err: any) {
      // Session expired or lost mid-page: fall back to the logged-out prompt.
      if (err.status === 401) user.set(null);
      error = err.issues?.[0]?.msg ?? err.message ?? 'Submission failed';
    } finally {
      pending = false;
    }
  }
</script>

<section class="comments">
  <p class="label">{comments.length} {comments.length === 1 ? 'response' : 'responses'}</p>

  {#if $ready && $user}
    <form onsubmit={submit}>
      <div class="as"><span class="avatar">{handle.slice(0, 1).toUpperCase()}</span>Commenting as <strong>{handle}</strong></div>
      <textarea bind:value={body} placeholder="Add to the conversation…" required maxlength="1000" rows="3"></textarea>
      {#if error}<p class="err">{error}</p>{/if}
      <button disabled={pending}>{pending ? 'Posting…' : 'Post response'}</button>
    </form>
  {:else if $ready}
    <p class="gate-note">Sign in to join the conversation.</p>
    <AuthForm />
  {/if}

  <ul>
    {#each comments as c (c.id)}
      <li>
        <span class="avatar">{c.name.slice(0, 1).toUpperCase()}</span>
        <div class="content">
          <header>
            <strong>{c.name}</strong>
            <time>{new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</time>
          </header>
          <p>{c.body}</p>
        </div>
      </li>
    {/each}
  </ul>
</section>

<style>
  .label {
    font-family: var(--font-mono); font-size: 0.72rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--muted); margin: 0 0 1.3rem;
  }
  .gate-note { color: var(--muted); font-size: 0.95rem; margin: 0 0 1rem; }

  .avatar {
    display: inline-flex; align-items: center; justify-content: center;
    width: 1.9rem; height: 1.9rem; flex: none;
    border-radius: 50%; background: var(--surface-2); border: 1px solid var(--rule);
    font-family: var(--font-mono); font-size: 0.8rem; font-weight: 500; color: var(--accent);
  }

  form {
    display: flex; flex-direction: column; gap: 0.85rem;
    margin-bottom: 2.5rem;
    padding: 1.4rem;
    background: var(--surface);
    border: 1px solid var(--rule);
    border-radius: 14px;
  }
  .as { display: flex; align-items: center; gap: 0.6rem; font-size: 0.88rem; color: var(--muted); }
  .as strong { color: var(--fg); font-weight: 600; }
  textarea {
    background: var(--bg); color: var(--fg);
    border: 1px solid var(--rule); border-radius: 9px;
    padding: 0.75rem 0.85rem; font: inherit; line-height: 1.6; resize: vertical;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  textarea:focus {
    outline: none; border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
  }
  button {
    align-self: flex-start;
    background: var(--accent); color: var(--accent-ink);
    border: none; border-radius: 9px;
    padding: 0.6rem 1.15rem; cursor: pointer;
    font: inherit; font-weight: 600;
    transition: filter 0.15s ease, transform 0.06s ease;
  }
  button:hover:not(:disabled) { filter: brightness(1.06); }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: 0.6; cursor: progress; }
  .err { color: #ff8f7a; font-size: 0.9rem; margin: 0; }

  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1.6rem; }
  li { display: flex; gap: 0.9rem; }
  .content { flex: 1; min-width: 0; }
  li header { display: flex; align-items: baseline; gap: 0.7rem; margin-bottom: 0.3rem; }
  li strong { font-weight: 600; }
  li time { font-family: var(--font-mono); color: var(--muted); font-size: 0.74rem; }
  li p { margin: 0; line-height: 1.6; color: var(--fg); }
</style>
