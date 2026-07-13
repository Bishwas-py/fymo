<script>
  import { format } from 'date-fns';
  
  let { message = "Hello from Test component!" } = $props();
  
  const currentDate = format(new Date(), 'PPP');
</script>

<div class="test-component">
  <h3>{message}</h3>
  <p>This is a test component that can be imported!</p>
  <p><strong>Current date:</strong> {currentDate}</p>
</div>

<style>
  .test-component {
    background: #f0f8ff;
    border: 2px solid #4a90e2;
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
  }
  
  .test-component h3 {
    color: #2c5aa0;
    margin: 0 0 0.5rem 0;
  }
  
  .test-component p {
    color: #666;
    margin: 0;
  }
</style>