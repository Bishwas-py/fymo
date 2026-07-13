"""
Development server command
"""

import subprocess
import sys
from pathlib import Path
from fymo.utils.colors import Color
from fymo.server.gunicorn import run_prod


def run_server(host: str = '127.0.0.1', port: int = 8000, reload: bool = True,
               prod: bool = False, workers: int = 4):
    """
    Run the server

    Args:
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload (dev mode only)
        prod: Serve via gunicorn instead of the wsgiref dev server
        workers: Number of gunicorn worker processes (prod mode only)
    """
    Color.print_info(f"Starting Fymo {'production' if prod else 'development'} server at http://{host}:{port}")

    # Check if server.py exists
    server_file = Path.cwd() / 'server.py'
    if not server_file.exists():
        Color.print_error("server.py not found! Are you in a Fymo project directory?")
        return

    # For development, use Python's built-in server to avoid STPyV8/gunicorn conflicts.
    # For production, --prod boots gunicorn via fymo.server.gunicorn.run_prod.
    if reload and not prod:
        Color.print_warning("Note: Auto-reload is not available withe built-in server. Restart manually for changes.")

    try:
        # Import and run the app directly
        sys.path.insert(0, str(Path.cwd()))
        from server import app

        if prod:
            Color.print_success(f"Starting gunicorn with {workers} worker(s) at http://{host}:{port}")
            run_prod(app, host, port, workers)
            return

        # Threaded dev server — concurrent requests, so one slow handler
        # or open SSE subscription never freezes the whole process.
        from fymo.server.dev import make_dev_server

        Color.print_success(f"Server running at http://{host}:{port}")
        Color.print_info("Press Ctrl+C to stop...")

        with make_dev_server(host, port, app) as httpd:
            httpd.serve_forever()

    except ImportError as e:
        Color.print_error(f"Failed to import server: {e}")
        Color.print_info("Make sure you're in a Fymo project directory")
    except KeyboardInterrupt:
        Color.print_info("\nShutting down server...")
    except Exception as e:
        Color.print_error(f"Failed to start server: {e}")


def run_dev_server(app, host: str = '127.0.0.1', port: int = 8000):
    """
    Run development server directly with a WSGI app
    
    Args:
        app: WSGI application
        host: Host to bind to
        port: Port to bind to
    """
    from fymo.server.dev import make_dev_server

    Color.print_info(f"Starting development server at http://{host}:{port}")
    Color.print_warning("This server is for development only. Use a production WSGI server for deployment.")

    try:
        with make_dev_server(host, port, app) as httpd:
            Color.print_success(f"Server running at http://{host}:{port}")
            print("Press Ctrl+C to stop...")
            httpd.serve_forever()
    except KeyboardInterrupt:
        Color.print_info("\nShutting down server...")
    except Exception as e:
        Color.print_error(f"Server error: {e}")
