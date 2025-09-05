<script>
  let { id, content } = $props();
  
  let count = $state(12);
  let doubled = $derived(count * 2);
  
  function increment() {
    count++;
    console.log('increament worked:', count);
  }

  $effect(() => {
    console.log('count is', count);
  });
</script>

<div class="post">
  <h1>Post #{id}</h1>
  <p>{content}</p>
  
  <div class="counter">
    <p>Count: {count} (doubled: {doubled})</p>
    <button onclick={increment}>Increment</button>
    {#if count > 30}
      <p>Count is greater than 10</p>
    {/if}
  </div>
</div>

<style>
  .post {
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 8px;
    max-width: 600px;
    margin: 2rem auto;
    font-family: Arial, sans-serif;
  }
  
  .counter {
    margin-top: 1rem;
    padding: 0.5rem;
    background: #f5f5f5;
    border-radius: 4px;
  }
  
  button {
    background: #007acc;
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
  }
  
  button:hover {
    background: #005a9e;
  }
</style>