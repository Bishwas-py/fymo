<script lang="ts">
  let { go_to_login }: { go_to_login: () => Promise<void> } = $props();
</script>

<header class="head">
  <p class="kicker">Demo</p>
  <h1>Redirect primitive</h1>
  <p class="dek">Exercises <code>fymo.remote.Redirect</code> end to end.</p>
</header>

<button id="go-to-login" onclick={() => go_to_login()}>Go to login</button>

<style>
  .kicker {
    font-family: var(--font-mono); font-size: 0.72rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--muted); margin: 0;
  }
  .head { margin-bottom: 2.5rem; }
  .head h1 { font-size: clamp(2rem, 5.5vw, 2.6rem); font-weight: 700; margin: 0.6rem 0 0.4rem; }
  .dek { color: var(--muted); margin: 0; }

  button {
    background: var(--accent); color: var(--accent-ink);
    border: none; border-radius: 9px;
    padding: 0.6rem 1.15rem; cursor: pointer;
    font: inherit; font-weight: 600;
  }
</style>
