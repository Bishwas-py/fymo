#!/usr/bin/env python3
"""Entry point for the blog app."""
from pathlib import Path
from fymo import create_app

PROJECT_ROOT = Path(__file__).resolve().parent

# Lazy-import the seeder so this file imports cleanly even before Task 19
# adds it. ensure_seeded() seeds the SQLite DB from app/posts/*.md on first run.
try:
    from app.lib.seeder import ensure_seeded
    ensure_seeded(PROJECT_ROOT)
except ImportError:
    pass

app = create_app(PROJECT_ROOT)

if __name__ == "__main__":
    from fymo.cli.commands.serve import run_dev_server
    run_dev_server(app)
