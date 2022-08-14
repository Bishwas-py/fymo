import re
from pathlib import Path
import os
BASE_DIR = Path(__file__).resolve().parent
template_path = "templates"
def render_template(template_name="index.html"):
    return "<h1>Hello</h1>"


templates_dir = os.listdir(BASE_DIR / template_path)

paths = {}
for file_name in templates_dir:
    path_name = re.sub(r'\.pml$', '', file_name)
    if path_name == "index":
        path_name = "/"
    paths.update(
        {
            path_name: file_name
        }
    )

def app(environ, start_response):
    print(paths)
    data = render_template()
    data = data.encode("utf-8")

    start_response(
        f"200 OK", [
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(data)))
        ]
    )

    return iter([data])