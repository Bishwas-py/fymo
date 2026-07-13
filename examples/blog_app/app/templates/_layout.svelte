<script>
  import Nav from './_shared/Nav.svelte';
  let { children } = $props();
</script>

<Nav />
{@render children()}
