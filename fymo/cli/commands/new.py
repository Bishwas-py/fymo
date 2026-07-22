"""
Create new Fymo projects

The scaffold lives as inert template files in fymo/cli/templates/project/
(same ownership model as `fymo generate auth`: rendered copies become the
app's code, fymo never imports them at runtime). This module is the
manifest: which template lands where, which directories exist even when
empty, plus the fymo.yml rendered through the shared _scaffold module so
`fymo new` and `fymo init` cannot drift apart.
"""

from pathlib import Path
from fymo.utils.colors import Color
from fymo.cli.render import render
from fymo.cli.writer import PlannedFile, execute_plan
from fymo.cli.commands._scaffold import render_fymo_yml
from fymo.cli.commands.generate_auth import write_auth_files

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "project"

# Notes on individual files (rationale kept from the inline era):
# - tsconfig.json: $lib/*, $components/*, $remote/* (codegen output) and
#   $auth aliases so imports never need brittle relative paths. There is
#   no separate server-only alias: the server/client boundary in fymo is
#   language, not directory convention; app/controllers/*.py and
#   app/remote/*.py are server-only by construction.
# - server.py: plain WSGI entrypoint for gunicorn/uwsgi/`fymo serve
#   --prod`; local development runs through `fymo dev`, which builds its
#   own FymoApp, so a `python server.py` entrypoint is deliberately not
#   offered. Executable bit set below.
# - app/templates/_layout.svelte: root layout; its CSS import is what
#   puts app/assets/app.css on every page.
# - app/static/favicon.svg: placeholder mark served at /favicon.svg via
#   the root-static allowlist, referenced from the root layout.
_BASE_FILES = {
    "requirements.txt.tmpl": "requirements.txt",
    "package.json.tmpl": "package.json",
    "tsconfig.json.tmpl": "tsconfig.json",
    "gitignore.tmpl": ".gitignore",
    "server.py.tmpl": "server.py",
    "app/static/favicon.svg.tmpl": "app/static/favicon.svg",
    "app/assets/app.css.tmpl": "app/assets/app.css",
    "app/templates/_layout.svelte.tmpl": "app/templates/_layout.svelte",
    "app/controllers/home.py.tmpl": "app/controllers/home.py",
    "app/templates/home/index.svelte.tmpl": "app/templates/home/index.svelte",
    "README.md.tmpl": "README.md",
}

# The signin page that makes the default auth flow reachable in the
# browser with zero manual wiring; the auth files themselves come from
# write_auth_files (the same templates `fymo generate auth` renders).
_SIGNIN_FILES = {
    "app/controllers/signin.py.tmpl": "app/controllers/signin.py",
    "app/templates/signin/index.svelte.tmpl": "app/templates/signin/index.svelte",
}

# Directories that exist even when the scaffold ships no file in them.
_DIRECTORIES = [
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

# Package markers; app/support/ is the Python-only home for shared
# server-side utilities (db helpers, env config) that don't belong in
# app/lib/ (TypeScript/Svelte-only) or the other app/ subpackages.
_APP_INIT = '"""Application package"""'
_SUPPORT_INIT = '"""Shared server-side utilities"""'


def _build_plan(name: str, auth: bool) -> list:
    tokens = {"project_name": name}
    plan = [
        PlannedFile("fymo.yml", render_fymo_yml(name, signin_route=auth)),
        PlannedFile("app/__init__.py", _APP_INIT),
        PlannedFile("app/support/__init__.py", _SUPPORT_INIT),
    ]
    manifest = dict(_BASE_FILES)
    if auth:
        manifest.update(_SIGNIN_FILES)
    for tmpl_rel, out_rel in manifest.items():
        content = render((_TEMPLATES_DIR / tmpl_rel).read_text(), tokens)
        chmod = 0o755 if out_rel == "server.py" else None
        plan.append(PlannedFile(out_rel, content, chmod=chmod))
    return plan


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

    project_path.mkdir()
    for directory in _DIRECTORIES:
        (project_path / directory).mkdir(parents=True, exist_ok=True)

    execute_plan(project_path, _build_plan(name, auth), command="fymo new")
    if auth:
        write_auth_files(project_path, 'password')

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
