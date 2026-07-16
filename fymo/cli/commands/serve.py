"""
Development server command
"""

import os
import sys
from pathlib import Path
from fymo.utils.colors import Color
from fymo.server.gunicorn import run_prod


def _granian_available() -> bool:
    from importlib.util import find_spec
    return find_spec("granian") is not None


def _resolve_prod_server(server: str) -> str:
    """Resolve the --server choice to a concrete server name.

    Auto mode prefers granian for throughput (issue #39) but never fails
    when it's absent; the fallback is logged so the choice stays
    observable. An explicit granian request with granian missing is a hard
    error, never a silent substitution.
    """
    if server == "auto":
        if _granian_available():
            Color.print_info("Auto-selected granian (installed); use --server gunicorn to override")
            return "granian"
        Color.print_info(
            "granian not installed, using gunicorn; pip install 'fymo[granian]' for higher throughput"
        )
        return "gunicorn"
    if server == "granian" and not _granian_available():
        Color.print_error(
            "granian is not installed. Install it with: pip install 'fymo[granian]'"
        )
        raise SystemExit(1)
    return server


def run_server(host: str = '127.0.0.1', port: int = 8000,
               prod: bool = False, workers: int = 4,
               server: str = 'auto'):
    """
    Run the server

    Args:
        host: Host to bind to
        port: Port to bind to
        prod: Serve via a production server instead of the dev pipeline
        workers: Number of worker processes (prod mode only, both servers)
        server: Production server: 'auto' (granian if installed, else
            gunicorn), 'granian', or 'gunicorn'
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

    resolved = _resolve_prod_server(server)

    if resolved == "granian":
        # Unlike the gunicorn path below, server.py must NOT be imported
        # here: each granian worker resolves the "server:app" target string
        # itself, building its own FymoApp and Node sidecar. An app built
        # in this parent would spawn a sidecar that nothing serves or
        # stops. See fymo/server/granian_server.py.
        from fymo.server import granian_server

        Color.print_success(f"Starting granian with {workers} worker(s) at http://{host}:{port}")
        try:
            granian_server.run_prod_granian(Path.cwd(), host, port, workers)
        except KeyboardInterrupt:
            Color.print_info("\nShutting down server...")
        return

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
