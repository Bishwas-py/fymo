<script lang="ts">
  import { login, signup } from '../../lib/auth';

  let { compact = false }: { compact?: boolean } = $props();

  let mode = $state<'login' | 'signup'>('login');
  let email = $state('');
  let password = $state('');
  let error: string | null = $state.raw(null);
  let pending = $state(false);

  const copy = $derived(
    mode === 'login'
      ? { eyebrow: '// members', title: 'Welcome back', cta: 'Log in' }
      : { eyebrow: '// join', title: 'Join the discussion', cta: 'Create account' }
  );

  function setMode(m: 'login' | 'signup') {
    mode = m;
    error = null;
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (pending) return;
    pending = true;
    error = null;
    try {
      if (mode === 'login') await login(email, password);
      else await signup(email, password);
    } catch (err: any) {
      error = err.issues?.[0]?.msg ?? err.message ?? 'Something went wrong. Try again.';
    } finally {
      pending = false;
    }
  }
</script>

<div class="auth" class:compact>
  <p class="eyebrow">{copy.eyebrow}</p>
  <h3>{copy.title}</h3>

  <div class="seg" role="tablist" aria-label="Authentication mode">
    <span class="thumb" class:right={mode === 'signup'} aria-hidden="true"></span>
    <button
      type="button" role="tab" aria-selected={mode === 'login'}
      class:on={mode === 'login'} onclick={() => setMode('login')}
    >Log in</button>
    <button
      type="button" role="tab" aria-selected={mode === 'signup'}
      class:on={mode === 'signup'} onclick={() => setMode('signup')}
    >Sign up</button>
  </div>

  <form onsubmit={submit}>
    <label>
      <span>Email</span>
      <input type="email" bind:value={email} placeholder="you@example.com"
             required autocomplete="email" />
    </label>
    <label>
      <span>Password</span>
      <input type="password" bind:value={password}
             placeholder={mode === 'signup' ? 'At least 8 characters' : '••••••••'}
             required minlength="8"
             autocomplete={mode === 'login' ? 'current-password' : 'new-password'} />
    </label>

    {#if error}<p class="err" role="alert">{error}</p>{/if}

    <button class="go" disabled={pending}>
      {#if pending}
        <span class="spinner" aria-hidden="true"></span>Working…
      {:else}
        {copy.cta}<span class="arrow" aria-hidden="true">→</span>
      {/if}
    </button>
  </form>
</div>

<style>
  .auth {
    display: flex; flex-direction: column;
    padding: 1.75rem;
    background: var(--surface);
    border: 1px solid var(--rule);
    border-radius: 16px;
  }
  .auth.compact { padding: 1.4rem; }

  .eyebrow {
    margin: 0 0 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); opacity: 0.9;
  }
  h3 { margin: 0 0 1.25rem; font-size: 1.4rem; letter-spacing: -0.02em; font-weight: 700; }

  /* Segmented toggle with a sliding thumb. */
  .seg {
    position: relative;
    display: grid; grid-template-columns: 1fr 1fr;
    padding: 4px; margin-bottom: 1.25rem;
    background: var(--bg);
    border: 1px solid var(--rule);
    border-radius: 10px;
  }
  .seg .thumb {
    position: absolute; top: 4px; left: 4px;
    width: calc(50% - 4px); height: calc(100% - 8px);
    background: var(--surface-2);
    border: 1px solid var(--rule);
    border-radius: 7px;
    transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .seg .thumb.right { transform: translateX(100%); }
  .seg button {
    position: relative; z-index: 1;
    background: none; border: none; cursor: pointer;
    padding: 0.5rem 0; font: inherit; font-weight: 600; font-size: 0.9rem;
    color: var(--muted); transition: color 0.18s ease;
  }
  .seg button.on { color: var(--fg); }

  form { display: flex; flex-direction: column; gap: 0.9rem; }
  label { display: flex; flex-direction: column; gap: 0.35rem; }
  label span { font-size: 0.8rem; color: var(--muted); }
  input {
    background: var(--bg); color: var(--fg);
    border: 1px solid var(--rule); border-radius: 8px;
    padding: 0.65rem 0.8rem; font: inherit;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  input::placeholder { color: color-mix(in srgb, var(--muted) 70%, transparent); }
  input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent);
  }

  .err {
    margin: 0; padding: 0.55rem 0.75rem;
    font-size: 0.85rem; color: #ffb4ab;
    background: color-mix(in srgb, #ff5c48 14%, transparent);
    border: 1px solid color-mix(in srgb, #ff5c48 35%, transparent);
    border-radius: 8px;
  }

  .go {
    display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem;
    margin-top: 0.35rem;
    background: var(--accent); color: #fff;
    border: none; border-radius: 8px;
    padding: 0.7rem 1rem; font: inherit; font-weight: 650; font-size: 0.95rem;
    cursor: pointer;
    transition: filter 0.15s ease, transform 0.05s ease;
  }
  .go:hover:not(:disabled) { filter: brightness(1.08); }
  .go:active:not(:disabled) { transform: translateY(1px); }
  .go:disabled { opacity: 0.75; cursor: progress; }
  .arrow { transition: transform 0.15s ease; }
  .go:hover:not(:disabled) .arrow { transform: translateX(3px); }

  .spinner {
    width: 0.9em; height: 0.9em;
    border: 2px solid rgba(255, 255, 255, 0.4);
    border-top-color: #fff; border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  @media (prefers-reduced-motion: reduce) {
    .seg .thumb, .arrow, .go { transition: none; }
    .spinner { animation-duration: 1.4s; }
  }
</style>
