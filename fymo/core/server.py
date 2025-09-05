"""
Fymo Server - Core WSGI application
"""

import json
import importlib
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional

from fymo.core.compiler import SvelteCompiler
from fymo.core.runtime import JSRuntime
from fymo.core.router import Router
from fymo.bundler.runtime_builder import ensure_svelte_runtime
from fymo.utils.colors import Color


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
        self.config = config or {}
        
        # Ensure Svelte runtime is built
        ensure_svelte_runtime(self.project_root)
        
        # Initialize core components
        self.compiler = SvelteCompiler()
        self.runtime = JSRuntime()
        self.router = Router(self.project_root / "config" / "routes.py")
        
        # Storage for compiled assets
        self.compiled_components = {}
        self.extracted_css = {}
        
        # Load configuration
        self._load_config()
    
    def _load_config(self):
        """Load configuration from fymo.yml or config files"""
        config_file = self.project_root / "fymo.yml"
        if config_file.exists():
            import yaml
            with open(config_file, 'r') as f:
                file_config = yaml.safe_load(f)
                self.config.update(file_config)
    
    def render_svelte_template(self, route_path: str) -> tuple[str, str]:
        """
        Render a Svelte component with SSR
        
        Args:
            route_path: The route path to render
            
        Returns:
            Tuple of (html, status_code)
        """
        try:
            # Get route info
            route_info = self.router.match(route_path)
            if not route_info:
                return self._render_404(), "404 NOT FOUND"
            
            # Get template and controller paths
            template_path = self.project_root / "app" / "templates" / route_info['template']
            controller_module = f"app.controllers.{route_info['controller']}"
            
            # Read Svelte component
            if not template_path.exists():
                return f"Template not found: {template_path}", "404 NOT FOUND"
                
            with open(template_path, 'r') as f:
                svelte_source = f.read()
            
            # Get controller context
            try:
                controller = importlib.import_module(controller_module)
                props = getattr(controller, 'context', {})
            except (ImportError, AttributeError) as e:
                print(f"{Color.FAIL}Controller error: {e}{Color.ENDC}")
                props = {}
            
            # Compile for SSR
            compiled = self.compiler.compile_ssr(svelte_source, str(template_path))
            
            if not compiled.get('success'):
                error_msg = compiled.get('error', 'Unknown compilation error')
                return f"<div>Svelte Compilation Error: {error_msg}</div>", "500 INTERNAL SERVER ERROR"
            
            # Render with JavaScript runtime
            render_result = self.runtime.render_component(compiled['js'], props, str(template_path))
            
            if 'error' in render_result:
                return f"<div>SSR Error: {render_result['error']}</div>", "500 INTERNAL SERVER ERROR"
            
            # Get rendered HTML
            html = render_result.get('html', '')
            
            # Extract CSS
            css = compiled.get('css', '')
            if css:
                component_name = template_path.stem
                self.extracted_css[f"{component_name}.css"] = css
            
            # Compile client-side version for hydration
            client_compiled = self.compiler.compile_dom(svelte_source, str(template_path))
            
            if client_compiled.get('success'):
                client_js = client_compiled.get('js', '')
                
                # Store compiled component
                component_name = template_path.stem
                self.compiled_components[f"{component_name}.js"] = client_js
                
                # Transform for hydration
                relative_template_path = str(template_path).replace(str(self.project_root) + '/', '')
                hydration_js = self.runtime.transform_client_js_for_hydration(
                    client_js, props, relative_template_path
                )
            else:
                hydration_js = "console.error('Client compilation failed');"
            
            # Generate full HTML page
            full_html = self._generate_html_page(html, props, hydration_js)
            
            return full_html, "200 OK"
            
        except Exception as e:
            print(f"{Color.FAIL}Render error: {e}{Color.ENDC}")
            return f"<div>Server Error: {str(e)}</div>", "500 INTERNAL SERVER ERROR"
    
    def _generate_html_page(self, content: str, props: Dict, hydration_js: str) -> str:
        """Generate full HTML page with hydration"""
        
        # Generate CSS links
        css_links = ""
        for css_file in self.extracted_css.keys():
            css_links += f'    <link rel="stylesheet" href="/assets/css/{css_file}">\n'
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{self.config.get('name', 'Fymo App')}</title>
{css_links}</head>
<body>
    <div id="svelte-app">{content}</div>
    <script id="svelte-props" type="application/json">{json.dumps(props)}</script>
    <script type="module">
        {hydration_js}
    </script>
</body>
</html>"""
    
    def _render_404(self) -> str:
        """Render 404 page"""
        return """<!DOCTYPE html>
<html>
<head>
    <title>404 - Not Found</title>
</head>
<body>
    <h1>404 - Page Not Found</h1>
    <p>The requested page could not be found.</p>
</body>
</html>"""
    
    def serve_asset(self, path: str) -> tuple[str, str, str]:
        """
        Serve static assets
        
        Returns:
            Tuple of (content, status, content_type)
        """
        try:
            if path.startswith('/assets/'):
                asset_path = path[8:]  # Remove '/assets/' prefix
                
                # Serve compiled components
                if asset_path.startswith('components/'):
                    component_file = asset_path[11:]
                    if component_file in self.compiled_components:
                        return self.compiled_components[component_file], "200 OK", "application/javascript"
                
                # Serve Svelte runtime
                elif asset_path.startswith('svelte/'):
                    return self._serve_svelte_runtime(asset_path), "200 OK", "application/javascript"
                
                # Serve CSS
                elif asset_path.startswith('css/'):
                    css_file = asset_path[4:]
                    if css_file in self.extracted_css:
                        return self.extracted_css[css_file], "200 OK", "text/css"
                
                # Serve static files
                else:
                    return self._serve_static_file(asset_path)
            
            return "Not found", "404 NOT FOUND", "text/plain"
            
        except Exception as e:
            print(f"{Color.FAIL}Asset serving error: {e}{Color.ENDC}")
            return str(e), "500 INTERNAL SERVER ERROR", "text/plain"
    
    def _serve_svelte_runtime(self, asset_path: str) -> str:
        """Serve bundled Svelte runtime"""
        if asset_path == 'svelte/client/index.js':
            runtime_path = self.project_root / 'dist' / 'svelte-runtime.js'
            if runtime_path.exists():
                with open(runtime_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return "console.error('Svelte runtime not found');"
        return ""
    
    def _serve_static_file(self, asset_path: str) -> tuple[str, str, str]:
        """Serve static files from app/static directory"""
        static_path = self.project_root / 'app' / 'static' / asset_path
        
        if static_path.exists() and static_path.is_file():
            content_type, _ = mimetypes.guess_type(str(static_path))
            if not content_type:
                content_type = 'application/octet-stream'
            
            with open(static_path, 'rb') as f:
                content = f.read()
            
            return content.decode('utf-8'), "200 OK", content_type
        
        return "File not found", "404 NOT FOUND", "text/plain"
    
    def __call__(self, environ, start_response):
        """WSGI application callable"""
        path = environ.get("PATH_INFO", "/")
        
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
