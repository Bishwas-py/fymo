import os
import re
from pathlib import Path

import yaml

from rigids import templates_root

BASE_DIR = Path(__file__).resolve().parent.parent
CURRENT_DIR = Path(__file__).resolve().parent


def get_routes():
    with open(CURRENT_DIR / 'routes.yml', 'r') as f:
        return yaml.load(f, Loader=yaml.FullLoader)


routes = get_routes()

paths = {}
root_path = routes.get('root')
# sets the global root path domain.com/
if root_path:
    file_name = f"{root_path.replace('.', '/')}.svelte"
    paths.update({
        '/': {'template_path': file_name, 'controller_path': root_path}
    })

resources = routes.get('resources')
if resources:
    for resource in resources:
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
