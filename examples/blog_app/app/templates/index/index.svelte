<script>
  let { posts = [] } = $props();
</script>
<h1>Blog</h1>
<ul>
  {#each posts as p}
    <li>{p.title}</li>
  {/each}
</ul>
