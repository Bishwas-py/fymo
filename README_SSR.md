# FyMo - Svelte 5 SSR Implementation

A full-stack monolith Python web framework with **Svelte 5 Server-Side Rendering** support.

## ✨ Features

- **Svelte 5 Support**: Full support for Svelte 5 runes (`$state`, `$derived`, `$props`)
- **Server-Side Rendering**: Real SSR using STPyV8 (Cloudflare's V8 bindings)
- **Production Ready**: Uses robust STPyV8 instead of experimental alternatives
- **WSGI Compatible**: Works with Gunicorn, uWSGI, and other WSGI servers
- **Hot Reloading**: Development server with automatic recompilation
- **Fallback Support**: Graceful degradation if JavaScript runtime fails

## 🚀 Quick Start

### Prerequisites
- Python 3.9+ (required for STPyV8)
- Node.js 18+ (for Svelte compiler)

### Installation

```bash
# Clone and setup
git clone <repo>
cd fymo

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
npm install

# Test setup
python setup.py
```

### Run Development Server

```bash
python -m gunicorn server:app --reload
```

Visit: http://localhost:8000/posts/index

## 📁 Project Structure

```
fymo/
├── server.py              # Main WSGI application
├── js_runtime.py          # STPyV8 JavaScript runtime
├── svelte_compiler.py     # Svelte 5 compiler wrapper
├── routes/
│   ├── config.py          # Route configuration
│   └── routes.yml         # Route definitions
├── controllers/           # Python controllers (provide props)
│   └── posts/
│       └── index.py       # Example controller
├── templates/             # Svelte 5 components
│   └── posts/
│       └── index.svelte   # Example Svelte 5 component
├── requirements.txt       # Python dependencies
├── package.json          # Node.js dependencies
└── setup.py              # Setup and testing script
```

## 🔧 How It Works

### 1. Request Flow
```
Request → routes.yml → Controller (Python) → Svelte Compiler → STPyV8 Runtime → SSR HTML → Response
```

### 2. Component Compilation
```
Component.svelte → Svelte Compiler → SSR JavaScript → STPyV8 Execution → HTML + CSS
```

### 3. Example Component

**Controller** (`controllers/posts/index.py`):
```python
def getContext() -> dict:
    return {
        "id": 1,
        "content": "Hello from FyMo with Svelte 5!"
    }

context = getContext()
```

**Template** (`templates/posts/index.svelte`):
```svelte
<script>
  // Svelte 5 runes syntax
  let { id, content } = $props();
  
  let count = $state(0);
  let doubled = $derived(count * 2);
  
  function increment() {
    count++;
  }
</script>

<div class="post">
  <h1>Post #{id}</h1>
  <p>{content}</p>
  
  <div class="counter">
    <p>Count: {count} (doubled: {doubled})</p>
    <button onclick={increment}>Increment</button>
  </div>
</div>

<style>
  .post {
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 8px;
  }
</style>
```

## 🛠 Technical Details

### Dependencies

**Python**:
- `gunicorn` - WSGI server
- `PyYAML` - YAML configuration parsing
- `stpyv8` - Cloudflare's V8 JavaScript runtime

**Node.js**:
- `svelte` - Svelte 5 framework and compiler

### STPyV8 Runtime

The JavaScript runtime uses STPyV8 for:
- **Robust V8 Integration**: Production-ready V8 bindings
- **Context Isolation**: Proper JavaScript context management
- **Error Handling**: Comprehensive JavaScript error reporting
- **Memory Management**: Automatic cleanup with context managers

### Svelte 5 Features Supported

- ✅ Runes (`$state`, `$derived`, `$effect`, `$props`)
- ✅ Server-side rendering
- ✅ Component composition
- ✅ Scoped styling
- ✅ Props injection from Python controllers
- ✅ Error boundaries

## 🔍 Development

### Adding New Routes

1. Add route to `routes/routes.yml`
2. Create controller in `controllers/`
3. Create Svelte component in `templates/`

### Debugging

- Check server logs for compilation errors
- Use browser dev tools for client-side issues
- STPyV8 provides detailed JavaScript stack traces

## 📈 Performance

- **Compilation Caching**: Svelte components are compiled once
- **Context Reuse**: STPyV8 contexts are efficiently managed
- **Memory Isolation**: Each request uses isolated JavaScript context
- **Error Recovery**: Graceful handling of compilation/runtime errors

## 🚧 Limitations

- Node.js required for Svelte compilation (temporary)
- STPyV8 requires Python 3.9+
- No client-side hydration yet (SSR only)
- Basic routing system

## 🎯 Future Roadmap

- [ ] Client-side hydration
- [ ] Hot module reloading
- [ ] TypeScript support
- [ ] Advanced routing
- [ ] Plugin system
- [ ] Production optimizations

## 📄 License

MIT License - see LICENSE file for details.
