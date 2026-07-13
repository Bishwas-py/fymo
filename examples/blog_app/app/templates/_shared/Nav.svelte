<script lang="ts">
  import { onMount } from 'svelte';
  import { user, ready, ensureLoaded, logout } from '../../lib/auth';
  import AuthForm from './AuthForm.svelte';

  let theme = $state<'dark' | 'light'>('dark');
  function toggle() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
  }

  let showLogin = $state(false);
  onMount(ensureLoaded);

  $effect(() => {
    if ($user) showLogin = false;
  });

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') showLogin = false;
  }
</script>

<svelte:head>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
  <link
    rel="stylesheet"
    href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
  />
</svelte:head>

<svelte:window onkeydown={onKey} />

<nav>
  <a href="/" class="brand">fymo<span class="dot">●</span>blog</a>
  <div class="right">
    {#if $ready && $user}
      <span class="who" title={$user.email}>{$user.email}</span>
      <button class="link" onclick={logout}>Sign out</button>
    {:else if $ready}
      <button class="cta" onclick={() => (showLogin = true)}>Sign in</button>
    {/if}
    <button class="theme" onclick={toggle} aria-label="Toggle theme">
      {theme === 'dark' ? '☀' : '☾'}
    </button>
  </div>
</nav>

{#if $ready && !$user && showLogin}
  <div
    class="overlay"
    role="button" tabindex="-1" aria-label="Close sign in"
    onclick={(e) => { if (e.target === e.currentTarget) showLogin = false; }}
    onkeydown={() => {}}
  >
    <div class="modal">
      <button class="close" onclick={() => (showLogin = false)} aria-label="Close">×</button>
      <AuthForm />
    </div>
  </div>
{/if}

<style>
  /* ---- Design tokens (apply to every route that renders <Nav />) ---- */
  :global(:root) {
    --bg: #0b0c0f;
    --surface: #131519;
    --surface-2: #191c22;
    --fg: #eceef2;
    --muted: #8a909c;
    --rule: #212530;
    --accent: #ff6a4d;
    --accent-ink: #ffffff;
    --code-bg: #131519;

    --font-display: "Space Grotesk", ui-sans-serif, system-ui, sans-serif;
    --font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --font-mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;

    --measure: 44rem;
  }
  :global(:root[data-theme="light"]) {
    --bg: #f7f5f0;
    --surface: #fffdf8;
    --surface-2: #f1eee7;
    --fg: #17181c;
    --muted: #5f636d;
    --rule: #e6e1d7;
    --accent: #e5482e;
    --accent-ink: #ffffff;
    --code-bg: #f1eee7;
  }

  :global(body) {
    background: var(--bg);
    color: var(--fg);
    font-family: var(--font-sans);
    font-size: 1.02rem;
    line-height: 1.7;
    margin: 0 auto;
    max-width: var(--measure);
    padding: 0 1.5rem 7rem;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }
  :global(h1, h2, h3, h4) {
    font-family: var(--font-display);
    letter-spacing: -0.02em;
    line-height: 1.12;
    font-weight: 600;
  }
  :global(a) { color: var(--accent); text-decoration: none; }
  :global(::selection) { background: color-mix(in srgb, var(--accent) 28%, transparent); }

  nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.6rem 0 1.3rem;
    margin-bottom: 3.5rem;
    border-bottom: 1px solid var(--rule);
  }
  .brand {
    font-family: var(--font-display);
    font-weight: 700;
    font-size: 1.15rem;
    color: var(--fg);
    letter-spacing: -0.03em;
  }
  .dot { color: var(--accent); font-size: 0.8em; margin: 0 0.05em; vertical-align: 0.08em; }

  .right { display: flex; align-items: center; gap: 1rem; }
  .who {
    font-family: var(--font-mono);
    color: var(--muted); font-size: 0.78rem;
    max-width: 13rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .link {
    background: none; border: none; color: var(--muted);
    cursor: pointer; font: inherit; font-size: 0.85rem; padding: 0;
    transition: color 0.15s ease;
  }
  .link:hover { color: var(--fg); }
  .cta {
    background: var(--accent); color: var(--accent-ink);
    border: none; border-radius: 8px;
    padding: 0.45rem 1rem; font: inherit; font-weight: 600; font-size: 0.85rem;
    cursor: pointer; transition: transform 0.06s ease, filter 0.15s ease;
  }
  .cta:hover { filter: brightness(1.06); }
  .cta:active { transform: translateY(1px); }
  .theme {
    background: none; border: 1px solid var(--rule); color: var(--fg);
    width: 2.1rem; height: 2.1rem; border-radius: 999px;
    cursor: pointer; font-size: 0.95rem; transition: background 0.15s ease;
  }
  .theme:hover { background: var(--surface); }

  .overlay {
    position: fixed; inset: 0; z-index: 50;
    display: flex; align-items: center; justify-content: center;
    padding: 1.5rem;
    background: color-mix(in srgb, #05060a 60%, transparent);
    backdrop-filter: blur(6px);
    animation: fade 0.16s ease;
  }
  .modal {
    position: relative; width: 100%; max-width: 24rem;
    box-shadow: 0 30px 70px -22px rgba(0, 0, 0, 0.7);
    animation: pop 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  .close {
    position: absolute; top: -0.7rem; right: -0.7rem; z-index: 1;
    width: 2rem; height: 2rem; border-radius: 50%;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--rule); cursor: pointer;
    font-size: 1.15rem; line-height: 1;
  }
  .close:hover { color: var(--fg); }
  @keyframes fade { from { opacity: 0; } }
  @keyframes pop { from { opacity: 0; transform: translateY(10px) scale(0.97); } }
  @media (prefers-reduced-motion: reduce) {
    .overlay, .modal { animation: none; }
  }
</style>
