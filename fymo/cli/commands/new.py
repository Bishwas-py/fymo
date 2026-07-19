"""
Create new Fymo projects
"""

import os
import shutil
from pathlib import Path
from fymo.utils.colors import Color
from fymo.cli.commands._scaffold import render_fymo_yml
from fymo.cli.commands.generate_auth import write_auth_files


def create_project(name: str, template: str = 'default', auth: bool = True):
    """
    Create a new Fymo project

    Args:
        name: Project name
        template: Template to use
        auth: Scaffold working password auth (app/auth/, app/remote/auth.py,
            signin page). False (`fymo new --no-auth`) skips it, for apps
            bringing their own identity (Clerk, pure APIs).
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
        'app/lib',
        'app/components',
        'app/support',
        'app/assets/fonts',
        'app/static',
        'dist',
        'tests',
    ]

    for directory in directories:
        (project_path / directory).mkdir(parents=True, exist_ok=True)

    # Create files
    create_project_files(project_path, name, auth=auth)
    if auth:
        write_auth_files(project_path, 'password')
        create_signin_page(project_path)

    Color.print_success(f"Project '{name}' created successfully!")
    Color.print_info(f"\nNext steps:")
    print(f"  cd {name}")
    print(f"  pip install -r requirements.txt")
    print(f"  npm install")
    print(f"  fymo dev")
    if auth:
        print()
        print("Password auth is ready out of the box: sign up and sign in at /signin.")
        print("The flow is yours to edit: app/auth/ (identity), app/remote/auth.py")
        print("(endpoints), app/templates/signin/index.svelte (the page). Protect a")
        print("route with `require_auth: true` in fymo.yml.")
    else:
        print()
        print("Scaffolded without auth (--no-auth). Add it later with")
        print("`fymo generate auth` (password), or --clerk / --skeleton variants.")


def create_project_files(project_path: Path, project_name: str, auth: bool = True):
    """Create default project files"""

    # fymo.yml
    fymo_yml = render_fymo_yml(project_name, signin_route=auth)
    (project_path / 'fymo.yml').write_text(fymo_yml)
    
    # requirements.txt: the granian extra pulls in the recommended
    # production server; gunicorn stays as the baseline fallback.
    requirements = """fymo[granian]>=0.1.0
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
    "dev": "fymo dev",
    "build": "fymo build"
  }},
  "dependencies": {{
    "devalue": "^5.8.1",
    "svelte": "^5.56.4"
  }},
  "devDependencies": {{
    "esbuild": "^0.25.9",
    "esbuild-svelte": "^0.9.0",
    "svelte-preprocess": "^6.0.3",
    "typescript": "^5.5.0"
  }}
}}
"""
    (project_path / 'package.json').write_text(package_json)

    # tsconfig.json — $lib/*, $components/*, and $remote/* aliases so imports
    # never need brittle relative paths. $remote/* points at codegen'd
    # output (populated by `fymo build`); $lib/* and $components/* point at
    # real source that already exists. There's no separate server-only
    # alias: the server/client boundary in fymo is language, not directory
    # convention — app/controllers/*.py and app/remote/*.py are server-only
    # by construction (Python never reaches the client bundle), so anything
    # that must stay off the client belongs there, not in app/lib/.
    tsconfig_json = """{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "paths": {
      "$remote/*": ["./dist/client/_remote/*"],
      "$auth": ["./dist/client/_auth"],
      "$lib/*": ["./app/lib/*"],
      "$components/*": ["./app/components/*"]
    }
  },
  "include": ["app/**/*.svelte", "app/**/*.ts"]
}
"""
    (project_path / 'tsconfig.json').write_text(tsconfig_json)

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
/data/
*.log

# IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store
"""
    (project_path / '.gitignore').write_text(gitignore)
    
    # server.py — plain WSGI entrypoint, for gunicorn/uwsgi/`fymo serve
    # --prod`. Local development runs through `fymo dev` (or its `fymo
    # serve` alias) instead, which builds its own FymoApp with dev=True and
    # a dev orchestrator; a `python server.py` entrypoint here would bypass
    # that pipeline entirely, so it's deliberately not offered.
    server_py = """#!/usr/bin/env python3
\"\"\"Entry point for Fymo application\"\"\"

from pathlib import Path
from fymo import create_app

# Get project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Create the WSGI application
app = create_app(PROJECT_ROOT)
"""
    (project_path / 'server.py').write_text(server_py)
    os.chmod(project_path / 'server.py', 0o755)
    
    # app/__init__.py
    (project_path / 'app' / '__init__.py').write_text('"""Application package"""')

    # app/support/__init__.py: Python-only home for shared server-side
    # utilities (db connection helpers, env config, etc.) that don't belong
    # in app/lib/ (TypeScript/Svelte-only) or any of the other app/
    # subpackages. Needs __init__.py like the other app/ subpackages so it
    # imports as app.support.* from day one.
    (project_path / 'app' / 'support' / '__init__.py').write_text('"""Shared server-side utilities"""')

    # app/static/favicon.svg: placeholder mark served at /favicon.svg via
    # the root-static allowlist, referenced from the root layout below.
    favicon_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#ff3e00"/>
  <circle cx="16" cy="16" r="8" fill="#fff"/>
  <circle cx="16" cy="16" r="3.5" fill="#ff3e00"/>
</svg>
"""
    (project_path / 'app' / 'static' / 'favicon.svg').write_text(favicon_svg)

    # app/assets/app.css: site-wide styles, a build input bundled through
    # the root layout's import below (hashed into dist/, never served raw).
    # Fonts referenced from here live in app/assets/fonts/.
    app_css = """:root {
  color-scheme: light dark;
}

body {
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
}
"""
    (project_path / 'app' / 'assets' / 'app.css').write_text(app_css)

    # app/templates/_layout.svelte: root layout wrapping every route. Its
    # CSS import is what puts app.css on every page; section layouts import
    # only what they add on top.
    root_layout = """<script>
  import '../assets/app.css';

  let { children } = $props();
</script>

<svelte:head>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</svelte:head>

{@render children()}
"""
    (project_path / 'app' / 'templates' / '_layout.svelte').write_text(root_layout)

    # app/controllers/home.py
    home_controller = """\"\"\"Home controller\"\"\"


def getContext():
    # Context data for the template, passed as props.
    return {
        'title': 'Welcome to Fymo',
        'message': 'Your Python SSR framework for Svelte 5 is ready!',
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
fymo dev
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
  - `assets/` - Build inputs (CSS, fonts, images) hashed into `/dist/`
  - `static/` - Verbatim files served at `/static/`
- `dist/` - Build output
- `tests/` - Tests
"""
    (project_path / 'README.md').write_text(readme)


def create_signin_page(project_path: Path):
    """Scaffold the signin route's controller and page.

    The auth files themselves come from write_auth_files (the same
    templates `fymo generate auth` renders); this adds the page that makes
    the flow reachable in the browser with zero manual wiring."""

    signin_controller = """\"\"\"Signin page controller.

The route named signin is auto-public and is where anonymous visitors are
redirected when a `require_auth: true` route turns them away. The form
lives in app/templates/signin/index.svelte.

The remote functions from app/remote/auth.py are threaded to the template
as props: on the client each becomes a typed fetch wrapper hitting the
real endpoint.
\"\"\"

from app.remote.auth import login, signup


def getContext():
    return {
        'title': 'Sign in',
        'login': login,
        'signup': signup,
    }
"""
    (project_path / 'app' / 'controllers' / 'signin.py').write_text(signin_controller)

    (project_path / 'app' / 'templates' / 'signin').mkdir(parents=True, exist_ok=True)
    signin_template = """<script>
  import { identity } from '$auth';

  // login/signup are the remote functions from app/remote/auth.py,
  // threaded through the controller context (see app/controllers/signin.py).
  // Do not import them as values from '$remote/auth' at the top level:
  // that alias is client-only and a value import breaks the page during
  // server-side rendering. `import type` from '$remote/auth' is fine.
  let { title, login, signup } = $props();

  let mode = $state('login');
  let email = $state('');
  let password = $state('');
  let error = $state('');
  let pending = $state(false);

  // require_auth redirects land here carrying the page the visitor wanted
  // as ?next=. Only local paths are honored; the server re-checks this.
  function nextPath() {
    const next = new URLSearchParams(window.location.search).get('next');
    return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
  }

  async function submit(event) {
    event.preventDefault();
    if (pending) return;
    pending = true;
    error = '';
    try {
      if (mode === 'signup') {
        // signup sets the session cookie itself; continue to where the
        // visitor was headed.
        await signup(email, password);
        window.location.assign(nextPath());
      } else {
        // login answers with a server-driven redirect to `next`; the
        // $remote client follows it, so success navigates by itself.
        await login(email, password, nextPath());
      }
    } catch (err) {
      error = err.message ?? 'Something went wrong';
      pending = false;
    }
  }
</script>

<div class="container">
  <h1>{title}</h1>

  {#if $identity}
    <!-- The $auth identity store carries the app/auth/public.py
         projection ({ uid, name } by default), hydrated at SSR and
         refreshed on every navigation. -->
    <p>Signed in as <strong>{$identity.name}</strong>. <a href="/">Back home</a></p>
  {:else}
    <form onsubmit={submit}>
      <label>
        Email
        <input type="email" bind:value={email} required />
      </label>
      <label>
        Password
        <input type="password" bind:value={password} required minlength="8" />
      </label>

      {#if error}
        <p class="error">{error}</p>
      {/if}

      <button type="submit" disabled={pending}>
        {mode === 'signup' ? 'Create account' : 'Sign in'}
      </button>
    </form>

    <p>
      {#if mode === 'login'}
        No account yet?
        <button class="link" onclick={() => (mode = 'signup')}>Sign up</button>
      {:else}
        Already have an account?
        <button class="link" onclick={() => (mode = 'login')}>Sign in</button>
      {/if}
    </p>
  {/if}
</div>

<style>
  .container {
    max-width: 400px;
    margin: 4rem auto;
    padding: 2rem;
    font-family: system-ui, -apple-system, sans-serif;
  }

  h1 {
    color: #ff3e00;
    margin-bottom: 1.5rem;
  }

  label {
    display: block;
    margin-bottom: 1rem;
  }

  input {
    display: block;
    width: 100%;
    margin-top: 0.25rem;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 1rem;
    box-sizing: border-box;
  }

  button[type='submit'] {
    background: #ff3e00;
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 1rem;
  }

  button[type='submit']:hover {
    background: #ff5722;
  }

  button[type='submit']:disabled {
    opacity: 0.6;
    cursor: default;
  }

  button.link {
    background: none;
    border: none;
    padding: 0;
    color: #ff3e00;
    cursor: pointer;
    font-size: 1rem;
    text-decoration: underline;
  }

  .error {
    color: #c00;
  }
</style>
"""
    (project_path / 'app' / 'templates' / 'signin' / 'index.svelte').write_text(signin_template)
