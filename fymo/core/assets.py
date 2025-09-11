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
        self.compiled_components: Dict[str, str] = {}
        self.extracted_css: Dict[str, str] = {}
    
    def store_compiled_component(self, name: str, content: str) -> None:
        """Store a compiled component"""
        self.compiled_components[name] = content
    
    def store_extracted_css(self, name: str, content: str) -> None:
        """Store extracted CSS"""
        self.extracted_css[name] = content
    
    def get_compiled_component(self, name: str) -> Optional[str]:
        """Get a compiled component"""
        return self.compiled_components.get(name)
    
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
            
            # Serve compiled components
            if asset_path.startswith('components/'):
                component_file = asset_path[11:]
                component_content = self.get_compiled_component(component_file)
                if component_content:
                    return component_content, "200 OK", "application/javascript"
            
            # Serve Svelte runtime
            elif asset_path == 'svelte-runtime.js':
                return self._serve_svelte_runtime()
            elif asset_path.startswith('svelte/'):
                return self._serve_svelte_runtime_path(asset_path), "200 OK", "application/javascript"
            
            # Serve CSS
            elif asset_path.startswith('css/'):
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
    
    def _serve_svelte_runtime(self) -> Tuple[str, str, str]:
        """Serve the main Svelte runtime"""
        runtime_path = self.project_root / 'dist' / 'svelte-runtime.js'
        if runtime_path.exists():
            try:
                with open(runtime_path, 'r', encoding='utf-8') as f:
                    return f.read(), "200 OK", "application/javascript"
            except IOError:
                pass
        
        return "console.error('Svelte runtime not found');", "200 OK", "application/javascript"
    
    def _serve_svelte_runtime_path(self, asset_path: str) -> str:
        """Serve bundled Svelte runtime by path"""
        if asset_path == 'svelte/client/index.js':
            runtime_path = self.project_root / 'dist' / 'svelte-runtime.js'
            if runtime_path.exists():
                try:
                    with open(runtime_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except IOError:
                    pass
        
        return "console.error('Svelte runtime not found');"
    
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
    
    def generate_css_links(self) -> str:
        """Generate CSS link tags for all extracted CSS"""
        css_links = ""
        for css_file in self.extracted_css.keys():
            css_links += f'    <link rel="stylesheet" href="/assets/css/{css_file}">\n'
        return css_links
