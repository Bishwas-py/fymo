"""
Shared fymo.yml scaffold for `fymo new` and `fymo init`.

Both commands used to hand-roll their own fymo.yml text and had quietly
drifted apart: `fymo init`'s template was missing the `build:` block that
`fymo new`'s included, with no indication the difference was intentional.
There should be exactly one fymo.yml shape; this module renders it so both
commands stay in sync by construction. This is `fymo new`'s former
template verbatim -- it was the richer of the two.
"""


def render_fymo_yml(project_name: str) -> str:
    """Render the default fymo.yml contents for a project named `project_name`."""
    return f"""# Fymo project configuration
name: {project_name}
version: 1.0.0

# Routing configuration
routes:
  root: home.index
  resources:
    - posts

# Remote functions (app/remote/*.py) require an explicit @remote marker to
# be browser-callable: file placement alone is not enough. Switch to
# mode: implicit-legacy only if migrating an older project that relies on
# implicit exposure.
remote:
  mode: strict

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
