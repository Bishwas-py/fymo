# Todo App - Fymo Example

A fully functional todo application built with Fymo framework, demonstrating Python SSR with Svelte 5.

## Features

- ✅ Add, complete, and delete todos
- 🎯 Filter todos (All, Active, Completed)
- 💾 Server-side rendering with Python
- ⚡ Client-side reactivity with Svelte 5 runes
- 🎨 Beautiful UI inspired by TodoMVC

## Tech Stack

- **Backend**: Python with Fymo framework
- **Frontend**: Svelte 5 with runes (`$state`, `$derived`)
- **SSR**: Full server-side rendering with client hydration

## Quick Start

### 1. Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# Node dependencies  
npm install
```

### 2. Copy the build script (if not present)

```bash
cp ../../fymo/bundler/js/build_runtime.js .
```

### 3. Start the Server

```bash
fymo serve
```

Or directly with Python:

```bash
python server.py
```

Visit `http://127.0.0.1:8000` to see the app!

## Project Structure

```
todo_app/
├── app/
│   ├── controllers/
│   │   └── todos.py        # Todo controller with initial data
│   ├── templates/
│   │   └── todos/
│   │       └── index.svelte # Todo app component
│   └── static/             # Static assets
├── config/
│   └── routes.py          # Route configuration
├── fymo.yml              # Project configuration
└── server.py             # Entry point
```

## How It Works

1. **Server-Side Rendering**: Python renders the initial HTML with todo data
2. **Hydration**: Svelte takes over on the client for interactivity
3. **Reactivity**: Uses Svelte 5's runes for reactive state management

## Key Code Examples

### Svelte 5 Runes in Action

```svelte
<script>
  // Props from server
  let { todos: initialTodos = [] } = $props();
  
  // Reactive state
  let todos = $state([...initialTodos]);
  let filter = $state('all');
  
  // Derived state
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
</script>
```

### Python Controller

```python
# app/controllers/todos.py
context = {
    'todos': [
        {'id': 1, 'text': 'Learn Fymo', 'completed': True},
        {'id': 2, 'text': 'Build awesome apps', 'completed': False}
    ]
}
```

## Features Demonstrated

- **Svelte 5 Runes**: `$state`, `$derived`, `$props`
- **Event Handling**: Click, keyboard events
- **Conditional Rendering**: Dynamic UI based on state
- **List Rendering**: Efficient keyed each blocks
- **Component Styling**: Scoped and global styles
- **Server Data**: Initial data from Python backend

## Extending the App

To persist todos, you could:

1. Add a database (SQLite, PostgreSQL)
2. Create API endpoints for CRUD operations
3. Use Svelte stores for global state
4. Add user authentication
5. Implement localStorage for offline support

## License

MIT - Part of the Fymo framework examples