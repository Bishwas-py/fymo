import re
import os
import importlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
template_path = "templates"

templates_dir = os.listdir(BASE_DIR / template_path)


def render_template(path, context={}):
    html_str = ""
    #  paths[path] gives filename i.e. index.svelte
    with open(BASE_DIR / f"templates/{paths[path]['fn']}", 'r') as f:
        html_str = f.read()
        mod = importlib.import_module(f"controllers.{paths[path]['ap']}")
        html_str = html_str.format(**mod.context)
        return html_str


paths = {}
for file_name in templates_dir:
    path = re.sub(r'\.svelte$', '', file_name)
    actual_path = path
    if path == "index":
        path = "/"
    paths.update(
        {
            path: {'fn': file_name, 'ap': actual_path}
        }
    )


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
