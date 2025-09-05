# Fymo Framework

<div align="center">
  <h3>Production-ready Python SSR Framework for Svelte 5</h3>
  <p>Build modern web applications with Python backend and Svelte 5 frontend</p>
</div>

## ✨ Features

- 🚀 **Server-Side Rendering (SSR)** - Full Svelte 5 SSR with Python
- ⚡ **Client-Side Hydration** - Seamless hydration with real Svelte runtime
- 🎯 **Svelte 5 Runes** - Full support for `$state`, `$derived`, `$effect`
- 📦 **Zero Configuration** - Works out of the box
- 🛠️ **CLI Tools** - Professional CLI for project management
- 🔥 **Hot Reload** - Development server with auto-reload
- 🏗️ **Production Ready** - Built for real-world applications

## 🚀 Quick Start

### Installation

```bash
pip install fymo
```

### Create a New Project

```bash
fymo new my-app
cd my-app
```

### Install Dependencies

```bash
pip install -r requirements.txt
npm install
```

### Start Development Server

```bash
fymo serve
```

Visit `http://127.0.0.1:8000` to see your app!

## 📁 Project Structure

```
my-app/
├── app/
│   ├── controllers/     # Python controllers
│   ├── templates/       # Svelte components
│   ├── models/         # Data models
│   └── static/         # Static assets
├── config/             # Configuration
├── fymo.yml           # Project configuration
├── server.py          # Entry point
└── requirements.txt   # Python dependencies
```

## 🎯 Example Component

```svelte
<!-- app/templates/home/index.svelte -->
<script>
  let { title, message } = $props();
  let count = $state(0);
  
  function increment() {
    count++;
  }
</script>

<div>
  <h1>{title}</h1>
  <p>{message}</p>
  <button onclick={increment}>
    Count: {count}
  </button>
</div>
```

```python
# app/controllers/home.py
context = {
    'title': 'Welcome to Fymo',
    'message': 'Build amazing apps with Python and Svelte 5!'
}
```

## 🛠️ CLI Commands

- `fymo new <project>` - Create a new project
- `fymo serve` - Start development server
- `fymo generate <type> <name>` - Generate components/controllers
- `fymo build` - Build for production

## 🔧 Configuration

Configure your project in `fymo.yml`:

```yaml
name: my-app
version: 1.0.0

routes:
  root: home.index
  resources:
    - posts
    - users

server:
  host: 127.0.0.1
  port: 8000
  reload: true
```

## 🏗️ Architecture

Fymo combines:
- **Python** for server-side logic and routing
- **Svelte 5** for reactive UI components
- **STPyV8** for JavaScript execution in Python
- **Real Svelte Runtime** for client-side hydration

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Built with [Svelte 5](https://svelte.dev)
- Powered by [STPyV8](https://github.com/cloudflare/stpyv8)
- Inspired by modern web frameworks

---

<div align="center">
  <strong>Built with ❤️ by the Fymo Team</strong>
</div>
