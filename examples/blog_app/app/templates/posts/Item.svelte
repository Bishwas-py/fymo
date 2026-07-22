<script>
  // One row of the posts list, linking to its detail page.
  // Grow it: add actions, swap the layout. It is a plain Svelte component.
  let { item } = $props();
</script>

<li class="card">
  <a class="title" href="/posts/{item.id}">{item.title}</a>
  <span class="by">by {item.created_by}</span>
</li>

<style>
  .card {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
    padding: 0.75rem 1rem;
  }

  .title {
    font-weight: 550;
  }

  .by {
    color: var(--muted);
    font-family: var(--mono);
    font-size: 0.75rem;
  }
</style>
