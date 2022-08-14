from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent


def get_routes():
    with open(BASE_DIR / 'routes.yml', 'r') as f:
        routes = yaml.load(f, Loader=yaml.FullLoader)
    return routes
