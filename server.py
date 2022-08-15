import re
import os
import importlib
from pathlib import Path

from routes.config import get_routes

BASE_DIR = Path(__file__).resolve().parent
templates_root = "templates"

routes = get_routes()

paths = {}

root_path = routes.get('root')
# sets the global root path domain.com/
if root_path:
    file_name = f"{root_path.replace('.', '/')}.svelte"
    paths.update({
        '/': {'template_path': file_name, 'controller_path': root_path}
    })

# sets template and controller path through given routes
resources = routes.get('resources')
print(f"resources {resources}")
if resources:
    for resource in resources:

        print(f"{templates_root}/{resource}")
        templates_dir = os.listdir(BASE_DIR / f"{templates_root}/{resource}")

        for template_file_name in templates_dir:
            no_extension_file_path = re.sub(r'\.svelte$', '', template_file_name)
            controller_path = f"{resource}.{no_extension_file_path}"
            template_path = f"{resource}/{template_file_name}"
            paths.update(
                {
                    f"{resource}/{no_extension_file_path}": {
                        'template_path': template_path,
                        'controller_path': controller_path
                    }
                }
            )


def render_template(path):
    """
    Renders template, where actual path is unformulated slash containing string.
    """
    if path != "/":
        path = path.lstrip('/')

    #  paths[path] gives filename i.e. index.svelte
    print(paths[path])
    with open(BASE_DIR / f"templates/{paths[path]['template_path']}", 'r') as f:
        html_str = f.read()
        print(paths[path])
        mod = importlib.import_module(f"controllers.{paths[path]['controller_path']}")
        html_str = html_str.format(**mod.context)
    return html_str


# main server handler
def app(environ, start_response):
    path = environ.get("PATH_INFO")
    data = render_template(path)
    data = data.encode("utf-8")
    start_response(
        f"200 OK", [
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(data)))
        ]
    )

    return iter([data])
