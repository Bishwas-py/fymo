"""
Fymo Server - Core WSGI application
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.template_renderer import TemplateRenderer
from fymo.core.router import Router
from fymo.bundler.runtime_builder import ensure_svelte_runtime


class FymoApp:
    """Main Fymo application class"""

    def __init__(self, project_root: Optional[Path] = None, config: Optional[Dict] = None):
        """
        Initialize Fymo application

        Args:
            project_root: Root directory of the project
            config: Configuration dictionary
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()

        # Ensure Svelte runtime is built
        ensure_svelte_runtime(self.project_root)

        # Initialize core components
        self.config_manager = ConfigManager(self.project_root, config)
        self.asset_manager = AssetManager(self.project_root)
        self.router = self._initialize_router()
        self.template_renderer = TemplateRenderer(
            self.project_root,
            self.config_manager,
            self.asset_manager,
            self.router
        )

        # New pipeline: sidecar + manifest cache
        self.sidecar = None
        self.manifest_cache = None
        if os.environ.get("FYMO_NEW_PIPELINE") == "1":
            from fymo.core.sidecar import Sidecar
            from fymo.core.manifest_cache import ManifestCache
            dist_dir = self.project_root / "dist"
            if (dist_dir / "sidecar.mjs").is_file():
                self.sidecar = Sidecar(dist_dir=dist_dir)
                self.sidecar.start()
                self.sidecar.ping()  # warm
                self.manifest_cache = ManifestCache(dist_dir=dist_dir)
                # Pass to template renderer
                self.template_renderer.sidecar = self.sidecar
                self.template_renderer.manifest_cache = self.manifest_cache

    def __del__(self):
        if getattr(self, 'sidecar', None) is not None:
            try:
                self.sidecar.stop()
            except Exception:
                pass
    
    def _initialize_router(self) -> Router:
        """Initialize router with appropriate configuration"""
        # Try fymo.yml first, fallback to config/routes.py, then empty router
        fymo_yml = self.project_root / "fymo.yml"
        routes_py = self.project_root / "config" / "routes.py"
        
        if fymo_yml.exists():
            return Router(fymo_yml)
        elif routes_py.exists():
            return Router(routes_py)
        else:
            # Return router without routes file - will use convention-based routing
            return Router()
    
    def render_svelte_template(self, route_path: str) -> tuple[str, str]:
        """
        Render a Svelte component with SSR
        
        Args:
            route_path: The route path to render
            
        Returns:
            Tuple of (html, status_code)
        """
        return self.template_renderer.render_template(route_path)
    
    
    def serve_asset(self, path: str) -> tuple[str, str, str]:
        """
        Serve static assets
        
        Returns:
            Tuple of (content, status, content_type)
        """
        return self.asset_manager.serve_asset(path)
    
    
    def __call__(self, environ, start_response):
        """WSGI application callable"""
        path = environ.get("PATH_INFO", "/")
        
        # Handle dist asset requests (content-hashed bundles with immutable caching)
        if path.startswith("/dist/"):
            rest = path[len("/dist/"):]
            body, status, content_type, headers = self.asset_manager.serve_dist_asset(rest)
            response_headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
            response_headers.extend(headers.items())
            start_response(status, response_headers)
            return [body]

        # Handle asset requests
        if path.startswith('/assets/'):
            content, status, content_type = self.serve_asset(path)
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content
            start_response(
                status, [
                    ("Content-Type", content_type),
                    ("Content-Length", str(len(content_bytes))),
                    ("Access-Control-Allow-Origin", "*"),
                    ("Cache-Control", "public, max-age=3600")
                ]
            )
            return iter([content_bytes])
        
        # Handle template requests
        html, status = self.render_svelte_template(path)
        html_bytes = html.encode("utf-8")
        start_response(
            status, [
                ("Content-Type", "text/html"),
                ("Content-Length", str(len(html_bytes)))
            ]
        )
        return iter([html_bytes])


def create_app(project_root: Optional[Path] = None, config: Optional[Dict] = None) -> FymoApp:
    """
    Factory function to create a Fymo application
    
    Args:
        project_root: Root directory of the project
        config: Configuration dictionary
        
    Returns:
        FymoApp instance
    """
    return FymoApp(project_root, config)
