<script lang="ts">
  let { children } = $props();
</script>

<p class="kicker">
  <a href="/" class="back">← fymo●blog</a>
</p>
{@render children()}

<style>
  .kicker { margin: 0 0 2.5rem; }
  .back {
    font-family: var(--font-mono); font-size: 0.78rem; letter-spacing: 0.04em;
    color: var(--muted); transition: color 0.15s ease;
  }
  .back:hover { color: var(--accent); }
</style>
