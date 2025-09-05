<script>
  let { title, message } = $props();
  let count = $state(0);
  
  function increment() {
    count++;
  }
</script>

<div class="container">
  <h1>{title}</h1>
  <p>{message}</p>
  
  <div class="counter">
    <p>Count: {count}</p>
    <button onclick={increment}>Increment</button>
  </div>
</div>

<style>
  .container {
    max-width: 800px;
    margin: 2rem auto;
    padding: 2rem;
    font-family: system-ui, -apple-system, sans-serif;
  }
  
  h1 {
    color: #ff3e00;
    margin-bottom: 1rem;
  }
  
  .counter {
    margin-top: 2rem;
    padding: 1rem;
    background: #f5f5f5;
    border-radius: 8px;
  }
  
  button {
    background: #ff3e00;
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1rem;
  }
  
  button:hover {
    background: #ff5722;
  }
</style>
