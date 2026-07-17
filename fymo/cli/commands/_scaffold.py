"""
Shared fymo.yml scaffold for `fymo new` and `fymo init`.

Both commands used to hand-roll their own fymo.yml text and had quietly
drifted apart: `fymo init`'s template was missing the `build:` block that
`fymo new`'s included, with no indication the difference was intentional.
There should be exactly one fymo.yml shape; this module renders it so both
commands stay in sync by construction. This is `fymo new`'s former
template verbatim -- it was the richer of the two.
"""


def render_fymo_yml(project_name: str, signin_route: bool = False) -> str:
    """Render the default fymo.yml contents for a project named `project_name`.

    `signin_route=True` adds the signin route entry (the require_auth
    redirect target by convention); `fymo new` passes it when scaffolding
    the default password auth, `fymo init` and `fymo new --no-auth` don't.
    """
    if signin_route:
        routes_block = """# Routing configuration. Protect any route or resource with
# `require_auth: true`; anonymous visitors are redirected to the route
# named signin (page at app/templates/signin/index.svelte).
routes:
  root: home.index
  signin: signin.index
  resources:
    - posts
"""
    else:
        routes_block = """# Routing configuration
routes:
  root: home.index
  resources:
    - posts
"""
    return f"""# Fymo project configuration
name: {project_name}
version: 1.0.0

{routes_block}
# Remote functions (app/remote/*.py) require an explicit @remote marker to
# be browser-callable: file placement alone is not enough. Switch to
# mode: implicit-legacy only if migrating an older project that relies on
# implicit exposure.
remote:
  mode: strict

# Files committed to git belong in app/static/. Files created at runtime
# (uploads, recordings, anything a job writes) live under storage:, and an
# expose: entry is what gives a storage directory a URL. Uncomment to use:
# storage:
#   provider: local
#   root: data
#   expose:
#     - prefix: /media/videos/
#       dir: videos
#       extensions: [webm]

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
