# fymo

Python web framework that server-renders real Svelte 5 components. One repo, one deploy: Python does the backend, Svelte does the page, hydration works.

If your backend can be JS, use SvelteKit, honestly. fymo is for when the backend is already Python, or you just want your small and medium projects in one codebase instead of a frontend repo, a backend repo, and an API layer between them.

## Quick start

You need Python 3.11+ and Node 20+ (the build shells out to esbuild).

```bash
pip install fymo
fymo new myapp
cd myapp
npm install
fymo dev
```

That's a running app at `http://127.0.0.1:8000` with working password sign-in at `/signin`. The auth code is generated into your project, plain Python and Svelte you can read and edit. Delete `app/auth/` if you don't want it, or scaffold without it: `fymo new myapp --no-auth`.

For production:

```bash
fymo build
fymo serve --prod    # granian if installed (pip install 'fymo[granian]'), else gunicorn
```

## How it works

Your `.svelte` files are compiled by esbuild at build time into hashed bundles. At runtime, one long-lived Node process renders them server-side per request (length-prefixed frames over stdio, no per-request Node startup), and the browser hydrates the result like any Svelte app. Svelte 5 runes work as normal: `$state`, `$derived`, `$effect`, `$props`.

Controllers are Python functions that return a dict, and that dict lands in your component as props:

```python
# app/controllers/home.py
def getContext():
    return {'greeting': 'hello from Python'}
```

```svelte
<!-- app/templates/home/index.svelte -->
<script>
  let { greeting } = $props();
</script>

<h1>{greeting}</h1>
```

For everything after the first render, functions under `app/remote/` become typed functions you import in Svelte. No serializer, no endpoint, no fetch code:

```python
# app/remote/posts.py
@remote
def list_posts() -> list[Post]:
    return list(_ITEMS)
```

```svelte
<script>
  import { list_posts } from '$remote/posts';
</script>
```

## Generators

The daily loop is typed for you:

```bash
fymo generate resource posts   # routed page + full CRUD remote + component + passing tests
fymo generate page about       # controller + template + route wired into fymo.yml
fymo generate remote comments  # typed remote module + test
fymo generate auth             # the whole auth flow, as your code (--clerk / --skeleton variants)
fymo destroy resource posts    # reverses a generation; refuses if you edited the files
```

Generated code is ordinary app code. fymo never imports its templates at runtime, never touches generated files again, and the templates themselves are overridable per project (`.fymo/templates/`). The examples in this repo are generator output, unedited.

## Configuration

```yaml
# fymo.yml
name: myapp
version: 1.0.0

routes:
  root: home.index
  signin: signin.index
  resources:
    - posts
```

A `resources` entry routes both `/posts` and `/posts/<id>`. Protect any route with `require_auth: true`; anonymous visitors get redirected to signin.

## Design rule

Anything misconfigured fails at boot, and the error message contains the exact fix. Nothing falls back silently. This applies everywhere: config, auth, routing, the build. If fymo ever fails quietly on you, that's a bug, please file it.

## Limitations

Node is required at build time and runtime (the SSR sidecar). It's WSGI, threaded via granian, not asyncio. There's no ORM and no data layer on purpose, bring your own. It's v0.20 and one maintainer, so things still break between versions, loudly, with instructions in the error.

## Project structure

```
myapp/
├── app/
│   ├── controllers/   # Python, getContext() per page
│   ├── templates/     # Svelte components, one dir per route
│   ├── remote/        # browser-callable typed functions
│   ├── auth/          # your identity code (generated, yours)
│   ├── assets/        # css and fonts, compiled and hashed
│   └── static/        # served verbatim (favicon, robots.txt)
├── schema/            # your database schema (yours to manage)
├── tests/             # pytest, with fymo.testing helpers
├── fymo.yml
└── server.py
```

## License

MIT
