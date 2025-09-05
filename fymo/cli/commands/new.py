"""
Create new Fymo projects
"""

import os
import shutil
from pathlib import Path
from fymo.utils.colors import Color


def create_project(name: str, template: str = 'default'):
    """
    Create a new Fymo project
    
    Args:
        name: Project name
        template: Template to use
    """
    project_path = Path.cwd() / name
    
    if project_path.exists():
        Color.print_error(f"Directory '{name}' already exists!")
        return
    
    Color.print_info(f"Creating new Fymo project: {name}")
    
    # Create project structure
    project_path.mkdir()
    
    # Create directories
    directories = [
        'app/controllers',
        'app/templates',
        'app/models',
        'app/static/css',
        'app/static/js',
        'app/static/images',
        'config',
        'dist',
        'tests',
    ]
    
    for directory in directories:
        (project_path / directory).mkdir(parents=True, exist_ok=True)
    
    # Create files
    create_project_files(project_path, name)
    
    Color.print_success(f"Project '{name}' created successfully!")
    Color.print_info(f"\nNext steps:")
    print(f"  cd {name}")
    print(f"  pip install -r requirements.txt")
    print(f"  npm install")
    print(f"  fymo serve")


def create_project_files(project_path: Path, project_name: str):
    """Create default project files"""
    
    # fymo.yml
    fymo_yml = f"""# Fymo project configuration
name: {project_name}
version: 1.0.0

# Routing configuration
routes:
  root: home.index
  resources:
    - posts

# Build configuration
build:
  output_dir: dist
  minify: false
  
# Server configuration  
server:
  host: 127.0.0.1
  port: 8000
  reload: true
"""
    (project_path / 'fymo.yml').write_text(fymo_yml)
    
    # requirements.txt
    requirements = """fymo>=0.1.0
gunicorn>=23.0.0
"""
    (project_path / 'requirements.txt').write_text(requirements)
    
    # package.json
    package_json = f"""{{
  "name": "{project_name}",
  "version": "1.0.0",
  "type": "module",
  "description": "A Fymo project",
  "scripts": {{
    "dev": "fymo serve",
    "build": "fymo build"
  }},
  "dependencies": {{
    "svelte": "^5.38.0"
  }},
  "devDependencies": {{
    "esbuild": "^0.25.0"
  }}
}}
"""
    (project_path / 'package.json').write_text(package_json)
    
    # .gitignore
    gitignore = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
*.egg-info/
dist/
build/

# Node
node_modules/
npm-debug.log*

# Fymo
/dist/
*.log

# IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store
"""
    (project_path / '.gitignore').write_text(gitignore)
    
    # server.py
    server_py = """#!/usr/bin/env python3
\"\"\"Entry point for Fymo application\"\"\"

from pathlib import Path
from fymo import create_app

# Get project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Create the WSGI application
app = create_app(PROJECT_ROOT)

if __name__ == "__main__":
    # Run development server
    from fymo.cli.commands.serve import run_dev_server
    run_dev_server(app)
"""
    (project_path / 'server.py').write_text(server_py)
    os.chmod(project_path / 'server.py', 0o755)
    
    # app/__init__.py
    (project_path / 'app' / '__init__.py').write_text('"""Application package"""')
    
    # config/routes.py
    routes_py = """\"\"\"Route configuration\"\"\"

routes = {
    '/': {
        'controller': 'home',
        'action': 'index',
        'template': 'home/index.svelte'
    }
}

resources = ['posts']
"""
    (project_path / 'config' / 'routes.py').write_text(routes_py)
    
    # app/controllers/home.py
    home_controller = """\"\"\"Home controller\"\"\"

# Context data for the template
context = {
    'title': 'Welcome to Fymo',
    'message': 'Your Python SSR framework for Svelte 5 is ready!'
}
"""
    (project_path / 'app' / 'controllers' / 'home.py').write_text(home_controller)
    
    # app/templates/home/index.svelte
    (project_path / 'app' / 'templates' / 'home').mkdir(parents=True, exist_ok=True)
    home_template = """<script>
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
"""
    (project_path / 'app' / 'templates' / 'home' / 'index.svelte').write_text(home_template)
    
    # README.md
    readme = f"""# {project_name}

A Fymo project - Python SSR framework for Svelte 5

## Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install Node dependencies:
   ```bash
   npm install
   ```

## Development

Start the development server:
```bash
fymo serve
```

Or:
```bash
python server.py
```

## Build for Production

```bash
fymo build
```

## Project Structure

- `app/` - Application code
  - `controllers/` - Python controllers
  - `templates/` - Svelte templates
  - `models/` - Data models
  - `static/` - Static assets
- `config/` - Configuration files
- `dist/` - Build output
- `tests/` - Tests
"""
    (project_path / 'README.md').write_text(readme)
