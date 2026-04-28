<script lang="ts">
  let theme = $state<'dark' | 'light'>('dark');
  function toggle() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
  }
</script>

<nav>
  <a href="/" class="brand">fymo<span class="dot">.</span>blog</a>
  <button class="theme" onclick={toggle} aria-label="Toggle theme">
    {theme === 'dark' ? '☀' : '☾'}
  </button>
</nav>

<style>
  /* Theme tokens — defined here so they apply to every route that includes <Nav />. */
  :global(:root) {
    --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e;
    --rule: #21262d; --card: #161b22; --accent: #58a6ff;
    --code-bg: #161b22;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  }
  :global(:root[data-theme="light"]) {
    --bg: #ffffff; --fg: #1f2328; --muted: #57606a;
    --rule: #d0d7de; --card: #f6f8fa; --accent: #0969da; --code-bg: #f6f8fa;
  }
  :global(body) {
    background: var(--bg); color: var(--fg);
    margin: 0 auto; max-width: 720px; padding: 0 1.5rem 6rem;
  }
  :global(h1, h2, h3) { letter-spacing: -0.02em; }
  :global(a) { color: var(--accent); text-decoration: none; }

  nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.5rem 0;
    border-bottom: 1px solid var(--rule);
    margin-bottom: 3rem;
  }
  .brand {
    font-weight: 700;
    font-size: 1.05rem;
    color: var(--fg);
    text-decoration: none;
    letter-spacing: -0.02em;
  }
  .dot { color: var(--accent); }
  .theme {
    background: none;
    border: 1px solid var(--rule);
    color: var(--fg);
    width: 2rem; height: 2rem;
    border-radius: 0.4rem;
    cursor: pointer;
    font-size: 1rem;
  }
  .theme:hover { background: var(--card); }
</style>
