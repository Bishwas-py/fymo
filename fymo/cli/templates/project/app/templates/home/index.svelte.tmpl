<script>
  import { identity } from '$auth';

  let { rendered_at, python_says } = $props();

  // Live only after hydration: the counter working is the proof that
  // Svelte took over this server-rendered page in your browser.
  let clicks = $state(0);
</script>

<main>
  <header>
    <p class="eyebrow">fymo dev</p>
    <h1>It's alive.</h1>
    <p class="sub">Rendered by Python, hydrated by Svelte. Each card below proves one piece.</p>
  </header>

  <section class="proofs">
    <article class="card">
      <p class="eyebrow">Server</p>
      <p class="value">{rendered_at}</p>
      <p class="how">{python_says}</p>
      <span class="chip">app/controllers/home.py</span>
    </article>

    <article class="card">
      <p class="eyebrow">Client</p>
      <p class="value">{clicks} <span class="unit">clicks</span></p>
      <p class="how">
        <button onclick={() => clicks++}>Prove hydration</button>
        If this counts, JavaScript owns the page now.
      </p>
      <span class="chip">app/templates/home/index.svelte</span>
    </article>

    <article class="card">
      <p class="eyebrow">Identity</p>
      <p class="value">
        {#if $identity}{$identity.uid}{:else}anonymous{/if}
      </p>
      <p class="how">
        {#if $identity}
          Resolved by your own code in app/auth/, projected here through the $auth store.
        {:else}
          No session yet. The resolvers in app/auth/ decide who you are; /signin starts one.
        {/if}
      </p>
      <span class="chip">app/auth/resolver.py</span>
    </article>
  </section>

  <p class="foot">Edit any file above; this page rebuilds itself.</p>
</main>

<style>
  main {
    max-width: 880px;
    margin: 0 auto;
    padding: 4.5rem 1.5rem 3rem;
  }

  .sub {
    color: var(--muted);
    margin: 0;
  }

  .proofs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 1rem;
    margin-top: 2.25rem;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .value {
    font-size: 1.5rem;
    font-weight: 650;
    letter-spacing: -0.02em;
    margin: 0;
    overflow-wrap: anywhere;
  }

  .unit {
    font-size: 0.9rem;
    font-weight: 400;
    color: var(--muted);
  }

  .how {
    color: var(--muted);
    font-size: 0.875rem;
    margin: 0;
    flex: 1;
  }

  .how button {
    margin-right: 0.5rem;
    margin-bottom: 0.35rem;
  }

  .chip {
    align-self: flex-start;
  }

  .foot {
    margin-top: 2rem;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.8rem;
  }
</style>
