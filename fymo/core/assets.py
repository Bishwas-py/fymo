"""
Asset management for Fymo applications
"""

import mimetypes
from pathlib import Path
from typing import Dict, Tuple, Optional

from fymo.core.exceptions import AssetError


class AssetManager:
    """Manages compiled assets and static files for Fymo applications"""
    
    def __init__(self, project_root: Path):
        """
        Initialize asset manager

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.extracted_css: Dict[str, str] = {}

    def store_extracted_css(self, name: str, content: str) -> None:
        """Store extracted CSS"""
        self.extracted_css[name] = content

    def get_extracted_css(self, name: str) -> Optional[str]:
        """Get extracted CSS"""
        return self.extracted_css.get(name)
    
    def serve_asset(self, path: str) -> Tuple[str, str, str]:
        """
        Serve static assets

        Args:
            path: Asset path (should start with /assets/)

        Returns:
            Tuple of (content, status, content_type)
        """
        try:
            if not path.startswith('/assets/'):
                return "Invalid asset path", "400 BAD REQUEST", "text/plain"

            asset_path = path[8:]  # Remove '/assets/' prefix

            # Serve CSS
            if asset_path.startswith('css/'):
                css_file = asset_path[4:]
                css_content = self.get_extracted_css(css_file)
                if css_content:
                    return css_content, "200 OK", "text/css"

            # Serve static files
            else:
                return self._serve_static_file(asset_path)

            return "Asset not found", "404 NOT FOUND", "text/plain"

        except AssetError as e:
            return f"Asset error: {e.message}", "404 NOT FOUND", "text/plain"
        except Exception as e:
            return f"Asset serving error: {str(e)}", "500 INTERNAL SERVER ERROR", "text/plain"

    def _serve_static_file(self, asset_path: str) -> Tuple[str, str, str]:
        """Serve static files from app/static directory"""
        static_path = self.project_root / 'app' / 'static' / asset_path
        
        if static_path.exists() and static_path.is_file():
            content_type, _ = mimetypes.guess_type(str(static_path))
            if not content_type:
                content_type = 'application/octet-stream'
            
            try:
                with open(static_path, 'rb') as f:
                    content = f.read()
                return content.decode('utf-8'), "200 OK", content_type
            except (IOError, UnicodeDecodeError):
                return "Error reading file", "500 INTERNAL SERVER ERROR", "text/plain"
        
        return "File not found", "404 NOT FOUND", "text/plain"
    
    def serve_dist_asset(self, path: str) -> Tuple[bytes, str, str, Dict[str, str]]:
        """Serve a file from <project>/dist/. Returns (body, status, content_type, extra_headers).

        path: the part after /dist/ (e.g. "client/todos.A1B2.js")
        """
        import mimetypes as _mimetypes
        # Reject obvious traversal attempts
        if ".." in path.split("/") or "\x00" in path:
            return b"forbidden", "403 FORBIDDEN", "text/plain", {}

        dist_root = (self.project_root / "dist").resolve()
        target = (dist_root / path).resolve()

        # Defense in depth: ensure target is still within dist_root after resolution
        try:
            target.relative_to(dist_root)
        except ValueError:
            return b"forbidden", "403 FORBIDDEN", "text/plain", {}

        if not target.is_file():
            return b"not found", "404 NOT FOUND", "text/plain", {}

        content_type, _ = _mimetypes.guess_type(str(target))
        if content_type is None:
            content_type = "application/octet-stream"
        # Normalise JavaScript MIME type; older systems report text/javascript
        if content_type in ("text/javascript", "application/x-javascript"):
            content_type = "application/javascript"

        # Hashed filenames (anything in client/) get long-cache; manifest.json gets no-cache
        if path == "manifest.json":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"

        return target.read_bytes(), "200 OK", content_type, {"Cache-Control": cache}

    def generate_css_links(self) -> str:
        """Generate CSS link tags for all extracted CSS"""
        css_links = ""
        for css_file in self.extracted_css.keys():
            css_links += f'    <link rel="stylesheet" href="/assets/css/{css_file}">\n'
        return css_links
