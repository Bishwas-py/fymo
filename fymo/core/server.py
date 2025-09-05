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
        # Try fymo.yml first, fallback to config/routes.py
        fymo_yml = self.project_root / "fymo.yml"
        routes_py = self.project_root / "config" / "routes.py"
        
        if fymo_yml.exists():
            self.router = Router(fymo_yml)
        elif routes_py.exists():
            self.router = Router(routes_py)
        else:
            self.router = Router()
        
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
            
            # Get controller context and document metadata
            try:
                controller = importlib.import_module(controller_module)
                
                # Try dynamic getContext() function first, fallback to static context
                if hasattr(controller, 'getContext') and callable(getattr(controller, 'getContext')):
                    props = controller.getContext()
                else:
                    props = getattr(controller, 'context', {})
                
                # Get document metadata if available
                doc_meta = {}
                if hasattr(controller, 'getDoc') and callable(getattr(controller, 'getDoc')):
                    doc_meta = controller.getDoc()
                
            except (ImportError, AttributeError) as e:
                print(f"{Color.FAIL}Controller error: {e}{Color.ENDC}")
                props = {}
                doc_meta = {}
            
            # Compile for SSR
            compiled = self.compiler.compile_ssr(svelte_source, str(template_path))
            
            if not compiled.get('success'):
                error_msg = compiled.get('error', 'Unknown compilation error')
                return f"<div>Svelte Compilation Error: {error_msg}</div>", "500 INTERNAL SERVER ERROR"
            
            # Render with JavaScript runtime, passing controller for dynamic calls
            render_result = self.runtime.render_component(compiled['js'], props, str(template_path), controller)
            
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
                
                # Transform for hydration with context and doc data
                relative_template_path = str(template_path).replace(str(self.project_root) + '/', '')
                hydration_js = self.runtime.transform_client_js_for_hydration(
                    client_js, relative_template_path, props, doc_meta
                )
            else:
                hydration_js = "console.error('Client compilation failed');"
            
            # Generate full HTML page with document metadata
            full_html = self._generate_html_page(html, props, hydration_js, doc_meta)
            
            return full_html, "200 OK"
            
        except Exception as e:
            print(f"{Color.FAIL}Render error: {e}{Color.ENDC}")
            return f"<div>Server Error: {str(e)}</div>", "500 INTERNAL SERVER ERROR"
    
    def _generate_html_page(self, content: str, props: Dict, hydration_js: str, doc_meta: Dict = None) -> str:
        """Generate full HTML page with hydration and dynamic document metadata"""
        
        if doc_meta is None:
            doc_meta = {}
        
        # Generate CSS links
        css_links = ""
        for css_file in self.extracted_css.keys():
            css_links += f'    <link rel="stylesheet" href="/assets/css/{css_file}">\n'
        
        # Get title from doc metadata or config
        title = doc_meta.get('title', self.config.get('name', 'Fymo App'))
        
        # Generate structured head content safely
        head_content = self._generate_head_content(doc_meta.get('head', {}))
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
{css_links}{head_content}
</head>
<body>
    <div id="svelte-app">{content}</div>
    <script id="svelte-props" type="application/json">{json.dumps(props)}</script>
    <script type="module">
        {hydration_js}
    </script>
</body>
</html>"""
    
    def _generate_head_content(self, head_data: Dict) -> str:
        """
        Generate safe HTML head content from structured data
        
        Args:
            head_data: Dictionary containing 'meta' and 'script' data
            
        Returns:
            Formatted HTML string for head content
        """
        if not head_data:
            return ""
        
        head_parts = []
        
        # Generate meta tags
        meta_data = head_data.get('meta', [])
        if meta_data and isinstance(meta_data, list):
            for meta in meta_data:
                if isinstance(meta, dict):
                    meta_attrs = []
                    for key, value in meta.items():
                        # Escape HTML attributes safely
                        safe_key = self._escape_html_attr(str(key))
                        safe_value = self._escape_html_attr(str(value))
                        meta_attrs.append(f'{safe_key}="{safe_value}"')
                    
                    if meta_attrs:
                        head_parts.append(f'    <meta {" ".join(meta_attrs)}>')
        
        # Generate script tags
        script_data = head_data.get('script', {})
        if script_data and isinstance(script_data, dict):
            
            # Google Analytics
            analytics_id = script_data.get('analyticsID')
            if analytics_id:
                safe_analytics_id = self._escape_html_attr(str(analytics_id))
                head_parts.extend([
                    f'    <script async src="https://www.googletagmanager.com/gtag/js?id={safe_analytics_id}"></script>',
                    '    <script>',
                    '        window.dataLayer = window.dataLayer || [];',
                    '        function gtag(){dataLayer.push(arguments);}',
                    '        gtag("js", new Date());',
                    f'        gtag("config", "{safe_analytics_id}");',
                    '    </script>'
                ])
            
            # Hotjar
            hotjar_id = script_data.get('hotjar')
            if hotjar_id:
                safe_hotjar_id = self._escape_html_attr(str(hotjar_id))
                head_parts.extend([
                    '    <script>',
                    f'        (function(h,o,t,j,a,r){{',
                    f'            h.hj=h.hj||function(){{(h.hj.q=h.hj.q||[]).push(arguments)}};',
                    f'            h._hjSettings={{hjid:{safe_hotjar_id},hjsv:6}};',
                    f'            a=o.getElementsByTagName("head")[0];',
                    f'            r=o.createElement("script");r.async=1;',
                    f'            r.src=t+h._hjSettings.hjid+j+h._hjSettings.hjsv;',
                    f'            a.appendChild(r);',
                    f'        }})(window,document,"https://static.hotjar.com/c/hotjar-",".js?sv=");',
                    '    </script>'
                ])
            
            # Custom scripts
            custom_scripts = script_data.get('custom', [])
            if custom_scripts and isinstance(custom_scripts, list):
                if custom_scripts:
                    head_parts.append('    <script>')
                    for script in custom_scripts:
                        if isinstance(script, str) and script.strip():
                            # Basic JS safety - remove dangerous patterns
                            safe_script = self._sanitize_js(script.strip())
                            head_parts.append(f'        {safe_script}')
                    head_parts.append('    </script>')
        
        return '\n' + '\n'.join(head_parts) + '\n' if head_parts else ""
    
    def _escape_html_attr(self, value: str) -> str:
        """Escape HTML attribute values"""
        return (value.replace('&', '&amp;')
                     .replace('<', '&lt;')
                     .replace('>', '&gt;')
                     .replace('"', '&quot;')
                     .replace("'", '&#x27;'))
    
    def _sanitize_js(self, js_code: str) -> str:
        """Basic JavaScript sanitization - remove dangerous patterns"""
        # Remove potentially dangerous patterns
        dangerous_patterns = [
            'eval(',
            'Function(',
            'setTimeout(',
            'setInterval(',
            'document.write(',
            'innerHTML',
            'outerHTML',
            'document.cookie',
            'localStorage',
            'sessionStorage'
        ]
        
        sanitized = js_code
        for pattern in dangerous_patterns:
            if pattern.lower() in sanitized.lower():
                # Replace with safe comment
                sanitized = sanitized.replace(pattern, f'/* BLOCKED: {pattern} */')
        
        return sanitized
    
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
                elif asset_path == 'svelte-runtime.js':
                    runtime_path = self.project_root / 'dist' / 'svelte-runtime.js'
                    if runtime_path.exists():
                        with open(runtime_path, 'r', encoding='utf-8') as f:
                            return f.read(), "200 OK", "application/javascript"
                    else:
                        return "console.error('Svelte runtime not found');", "200 OK", "application/javascript"
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
