<script lang="ts">
  import type { ReactionCounts } from '$remote/posts';

  type ReactionKind = 'clap' | 'fire' | 'heart' | 'mind';

  let {
    slug,
    initial,
    toggle_reaction,
  }: {
    slug: string;
    initial: ReactionCounts;
    toggle_reaction: (slug: string, kind: ReactionKind) => Promise<ReactionCounts>;
  } = $props();

  let counts = $state(initial);
  let pending = $state(false);

  const KINDS: { kind: ReactionKind; emoji: string }[] = [
    { kind: 'clap', emoji: '👏' },
    { kind: 'fire', emoji: '🔥' },
    { kind: 'heart', emoji: '❤️' },
    { kind: 'mind', emoji: '🤯' },
  ];

  async function react(kind: ReactionKind) {
    if (pending) return;
    pending = true;
    try {
      counts = await toggle_reaction(slug, kind);
    } finally {
      pending = false;
    }
  }
</script>

<section class="reactions">
  {#each KINDS as { kind, emoji }}
    <button onclick={() => react(kind)} class:pending>
      <span class="emoji">{emoji}</span>
      <span class="count">{counts[kind]}</span>
    </button>
  {/each}
</section>

<style>
  .reactions {
    display: flex; gap: 0.6rem;
    margin: 3.5rem 0 2.5rem;
    padding: 1.4rem 0;
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
  }
  button {
    display: flex; align-items: center; gap: 0.5rem;
    background: var(--surface);
    border: 1px solid var(--rule);
    border-radius: 999px;
    padding: 0.45rem 1rem;
    color: var(--fg);
    cursor: pointer;
    font-size: 0.95rem;
    transition: transform 0.12s ease, border-color 0.15s ease, background 0.15s ease;
  }
  button:hover {
    transform: translateY(-2px);
    border-color: color-mix(in srgb, var(--accent) 55%, var(--rule));
    background: var(--surface-2);
  }
  button:active { transform: translateY(0); }
  button.pending { opacity: 0.5; }
  .emoji { font-size: 1.05rem; line-height: 1; }
  .count {
    font-family: var(--font-mono); font-size: 0.82rem; color: var(--muted);
    font-variant-numeric: tabular-nums; min-width: 1.2ch; text-align: left;
  }
</style>
