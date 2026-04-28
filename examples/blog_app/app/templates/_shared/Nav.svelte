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
