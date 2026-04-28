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
    display: flex; gap: 0.5rem;
    margin: 3rem 0 2rem;
    padding: 1rem 0;
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
  }
  button {
    display: flex; align-items: center; gap: 0.4rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 999px;
    padding: 0.4rem 0.9rem;
    color: var(--fg);
    cursor: pointer;
    font-size: 0.95rem;
    transition: transform 0.1s;
  }
  button:hover { transform: translateY(-1px); border-color: var(--accent); }
  button.pending { opacity: 0.5; }
  .count { font-variant-numeric: tabular-nums; min-width: 1.5ch; text-align: left; }
</style>
