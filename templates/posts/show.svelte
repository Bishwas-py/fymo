<script>
  // Svelte 5 runes syntax
  let { id, content } = $props();
</script>

<h1>#SHOW</h1>
<p>My id is #{id}, I write: {content}</p>

<style>
  h1 {
    color: #007acc;
    font-family: Arial, sans-serif;
  }
  
  p {
    font-family: Arial, sans-serif;
    color: #333;
  }
</style>