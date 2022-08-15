import importlib
from pathlib import Path

from rigids import SColor
from routes.config import paths

BASE_DIR = Path(__file__).resolve().parent


def render_template(path):
    """
    Renders template, where actual path is unformulated slash containing string.
    """
    if path != "/":
        path = path.lstrip('/')

    #  paths[path] gives filename i.e. index.svelte
    try:
        with open(BASE_DIR / f"templates/{paths[path]['template_path']}", 'r') as f:
            html_str = f.read()
            print(paths[path])
            mod = importlib.import_module(f"controllers.{paths[path]['controller_path']}")
            html_str = html_str.format(**mod.context)
        return html_str, "200 OK"
    except KeyError as e:
        error_message = f"400: {str(e)} not found"
        print(f"{SColor.FAIL}{error_message}{SColor.ENDC}")
        return f"{error_message}", "400 NOT FOUND"


# main server handler
def app(environ, start_response):
    path = environ.get("PATH_INFO")
    html_raw, response = render_template(path)
    html = html_raw.encode("utf-8")
    start_response(
        response, [
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(html)))
        ]
    )

    return iter([html])
