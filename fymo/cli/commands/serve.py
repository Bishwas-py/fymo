"""
Development server command
"""

import os
import sys
from pathlib import Path
from fymo.utils.colors import Color
from fymo.server.gunicorn import run_prod


def run_server(host: str = '127.0.0.1', port: int = 8000,
               prod: bool = False, workers: int = 4):
    """
    Run the server

    Args:
        host: Host to bind to
        port: Port to bind to
        prod: Serve via gunicorn instead of the dev pipeline
        workers: Number of gunicorn worker processes (prod mode only)
    """
    # Bare `fymo serve` (no --prod) earns no separate identity from `fymo
    # dev` -- issue #26: it used to boot the wsgiref server directly
    # against server.py's module-level app object, with no watcher, no
    # esbuild rebuild-on-save, no sidecar hot-reload, and whatever dev
    # value happened to be inherited from the shell. It's now a straight
    # alias for `fymo dev`.
    if not prod:
        from fymo.cli.commands.dev import run_dev
        run_dev(host, port)
        return

    Color.print_info(f"Starting Fymo production server at http://{host}:{port}")

    server_file = Path.cwd() / 'server.py'
    if not server_file.exists():
        Color.print_error("server.py not found! Are you in a Fymo project directory?")
        return

    # Force dev off before server.py is even imported, so a stray FYMO_DEV=1
    # left exported somewhere in the shell can't accidentally boot
    # production in dev mode (verbose tracebacks, insecure cookies, no rate
    # limiting). --prod must not trust whatever's inherited.
    os.environ["FYMO_DEV"] = "0"

    try:
        # Import and run the app directly
        sys.path.insert(0, str(Path.cwd()))
        from server import app

        Color.print_success(f"Starting gunicorn with {workers} worker(s) at http://{host}:{port}")
        run_prod(app, host, port, workers)

    except ImportError as e:
        Color.print_error(f"Failed to import server: {e}")
        Color.print_info("Make sure you're in a Fymo project directory")
    except KeyboardInterrupt:
        Color.print_info("\nShutting down server...")
    except Exception as e:
        Color.print_error(f"Failed to start server: {e}")
