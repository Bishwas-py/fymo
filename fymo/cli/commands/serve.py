"""
Development server command
"""

import subprocess
import sys
from pathlib import Path
from fymo.utils.colors import Color


def run_server(host: str = '127.0.0.1', port: int = 8000, reload: bool = True):
    """
    Run the development server
    
    Args:
        host: Host to bind to
        port: Port to bind to  
        reload: Enable auto-reload
    """
    Color.print_info(f"Starting Fymo development server at http://{host}:{port}")
    
    # Check if server.py exists
    server_file = Path.cwd() / 'server.py'
    if not server_file.exists():
        Color.print_error("server.py not found! Are you in a Fymo project directory?")
        return
    
    # Build command
    cmd = [
        sys.executable, '-m', 'gunicorn',
        'server:app',
        '--bind', f'{host}:{port}',
        '--workers', '1',
        '--threads', '2',
    ]
    
    if reload:
        cmd.append('--reload')
    
    try:
        # Run the server
        subprocess.run(cmd)
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
    from wsgiref.simple_server import make_server
    
    Color.print_info(f"Starting development server at http://{host}:{port}")
    Color.print_warning("This server is for development only. Use a production WSGI server for deployment.")
    
    try:
        with make_server(host, port, app) as httpd:
            Color.print_success(f"Server running at http://{host}:{port}")
            print("Press Ctrl+C to stop...")
            httpd.serve_forever()
    except KeyboardInterrupt:
        Color.print_info("\nShutting down server...")
    except Exception as e:
        Color.print_error(f"Server error: {e}")
