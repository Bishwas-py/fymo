<script>
  let { todos: initialTodos = [] } = $props();
  
  let todos = $state([...initialTodos]);
  let newTodoText = $state('');
  let filter = $state('all'); // all, active, completed
  
  let filteredTodos = $derived(() => {
    switch(filter) {
      case 'active':
        return todos.filter(t => !t.completed);
      case 'completed':
        return todos.filter(t => t.completed);
      default:
        return todos;
    }
  });
  
  let activeTodoCount = $derived(() => {
    return todos.filter(t => !t.completed).length;
  });
  
  let completedCount = $derived(() => {
    return todos.filter(t => t.completed).length;
  });
  
  function addTodo() {
    if (newTodoText.trim()) {
      todos = [...todos, {
        id: Date.now(),
        text: newTodoText.trim(),
        completed: false
      }];
      newTodoText = '';
    }
  }
  
  function toggleTodo(id) {
    todos = todos.map(todo => 
      todo.id === id ? { ...todo, completed: !todo.completed } : todo
    );
  }
  
  function deleteTodo(id) {
    todos = todos.filter(todo => todo.id !== id);
  }
  
  function clearCompleted() {
    todos = todos.filter(todo => !todo.completed);
  }
  
  function handleKeydown(event) {
    if (event.key === 'Enter') {
      addTodo();
    }
  }
</script>

<div class="todo-app">
  <header class="header">
    <h1>todos</h1>
    <input
      class="new-todo"
      placeholder="What needs to be done?"
      bind:value={newTodoText}
      onkeydown={handleKeydown}
      autofocus
    />
  </header>
  
  {#if todos.length > 0}
    <section class="main">
      <ul class="todo-list">
        {#each filteredTodos() as todo (todo.id)}
          <li class:completed={todo.completed}>
            <div class="view">
              <input
                class="toggle"
                type="checkbox"
                checked={todo.completed}
                onchange={() => toggleTodo(todo.id)}
              />
              <label>{todo.text}</label>
              <button class="destroy" onclick={() => deleteTodo(todo.id)}>×</button>
            </div>
          </li>
        {/each}
      </ul>
    </section>
    
    <footer class="footer">
      <span class="todo-count">
        <strong>{activeTodoCount()}</strong> {activeTodoCount() === 1 ? 'item' : 'items'} left
      </span>
      
      <ul class="filters">
        <li>
          <button
            class:selected={filter === 'all'}
            onclick={() => filter = 'all'}>
            All
          </button>
        </li>
        <li>
          <button
            class:selected={filter === 'active'}
            onclick={() => filter = 'active'}>
            Active
          </button>
        </li>
        <li>
          <button
            class:selected={filter === 'completed'}
            onclick={() => filter = 'completed'}>
            Completed
          </button>
        </li>
      </ul>
      
      {#if completedCount() > 0}
        <button class="clear-completed" onclick={clearCompleted}>
          Clear completed
        </button>
      {/if}
    </footer>
  {/if}
</div>

<style>
  .todo-app {
    background: #fff;
    margin: 130px auto 40px auto;
    position: relative;
    box-shadow: 0 2px 4px 0 rgba(0, 0, 0, 0.2),
                0 25px 50px 0 rgba(0, 0, 0, 0.1);
    max-width: 550px;
  }

  .header {
    position: relative;
  }

  h1 {
    position: absolute;
    top: -140px;
    width: 100%;
    font-size: 80px;
    font-weight: 200;
    text-align: center;
    color: #b83f45;
    text-rendering: optimizeLegibility;
    margin: 0;
  }

  .new-todo {
    position: relative;
    margin: 0;
    width: 100%;
    font-size: 24px;
    font-family: inherit;
    font-weight: inherit;
    line-height: 1.4em;
    color: inherit;
    padding: 16px 16px 16px 60px;
    border: none;
    background: rgba(0, 0, 0, 0.003);
    box-shadow: inset 0 -2px 1px rgba(0,0,0,0.03);
    box-sizing: border-box;
  }

  .new-todo::placeholder {
    font-style: italic;
    color: rgba(0, 0, 0, 0.4);
  }

  .main {
    position: relative;
    z-index: 2;
    border-top: 1px solid #e6e6e6;
  }

  .todo-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .todo-list li {
    position: relative;
    font-size: 24px;
    border-bottom: 1px solid #ededed;
    display: flex;
    align-items: center;
  }

  .todo-list li:last-child {
    border-bottom: none;
  }

  .todo-list li.completed label {
    color: #949494;
    text-decoration: line-through;
  }

  .view {
    display: flex;
    align-items: center;
    width: 100%;
    padding: 15px 15px 15px 60px;
  }

  .toggle {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 15px;
    width: 40px;
    height: 40px;
    margin: auto 0;
    border: none;
    appearance: none;
    cursor: pointer;
  }

  .toggle:before {
    content: '○';
    font-size: 28px;
    color: #e6e6e6;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
  }

  .toggle:checked:before {
    content: '✓';
    color: #5dc2af;
  }

  .view label {
    flex: 1;
    padding: 15px 15px 15px 0;
    margin-left: 45px;
    display: block;
    line-height: 1.2;
    word-break: break-all;
  }

  .destroy {
    display: none;
    position: absolute;
    top: 0;
    right: 10px;
    bottom: 0;
    width: 40px;
    height: 40px;
    margin: auto 0;
    font-size: 30px;
    color: #949494;
    transition: color 0.2s ease-out;
    background: none;
    border: none;
    cursor: pointer;
  }

  .destroy:hover,
  .destroy:focus {
    color: #C18585;
  }

  .todo-list li:hover .destroy {
    display: block;
  }

  .footer {
    padding: 10px 15px;
    height: 20px;
    text-align: center;
    font-size: 15px;
    border-top: 1px solid #e6e6e6;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .footer:before {
    content: '';
    position: absolute;
    right: 0;
    bottom: 0;
    left: 0;
    height: 50px;
    overflow: hidden;
    box-shadow: 0 1px 1px rgba(0, 0, 0, 0.2),
                0 8px 0 -3px #f6f6f6,
                0 9px 1px -3px rgba(0, 0, 0, 0.2),
                0 16px 0 -6px #f6f6f6,
                0 17px 2px -6px rgba(0, 0, 0, 0.2);
  }

  .todo-count {
    text-align: left;
    color: #777;
  }

  .filters {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    gap: 5px;
  }

  .filters button {
    color: inherit;
    margin: 3px;
    padding: 3px 7px;
    text-decoration: none;
    border: 1px solid transparent;
    border-radius: 3px;
    background: none;
    cursor: pointer;
    font-size: 14px;
  }

  .filters button:hover {
    border-color: #DB7676;
  }

  .filters button.selected {
    border-color: #CE4646;
  }

  .clear-completed {
    background: none;
    border: none;
    color: inherit;
    cursor: pointer;
    text-decoration: none;
    font-size: 14px;
  }

  .clear-completed:hover {
    text-decoration: underline;
  }

  /* Global styles for the page */
  :global(body) {
    font: 14px 'Helvetica Neue', Helvetica, Arial, sans-serif;
    line-height: 1.4em;
    background: #f5f5f5;
    color: #111111;
    min-width: 230px;
    max-width: 550px;
    margin: 0 auto;
    font-weight: 300;
  }

  :global(button) {
    margin: 0;
    padding: 0;
    border: 0;
    background: none;
    font-size: 100%;
    vertical-align: baseline;
    font-family: inherit;
    font-weight: inherit;
    color: inherit;
    appearance: none;
  }
</style>
