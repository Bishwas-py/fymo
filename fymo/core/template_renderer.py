"""
Template rendering for Fymo applications
"""

import importlib
import inspect
from pathlib import Path
from typing import Dict, Any, Tuple

from fymo.core.router import Router
from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.exceptions import TemplateError, CompilationError, RenderingError, ControllerError
from fymo.utils.colors import Color


class TemplateRenderer:
    """Handles Svelte template rendering with SSR"""

    def __init__(self, project_root: Path, config_manager: ConfigManager,
                 asset_manager: AssetManager, router: Router):
        """
        Initialize template renderer

        Args:
            project_root: Root directory of the project
            config_manager: Configuration manager instance
            asset_manager: Asset manager instance
            router: Router instance
        """
        self.project_root = project_root
        self.config_manager = config_manager
        self.asset_manager = asset_manager
        self.router = router
        self.sidecar = None
        self.manifest_cache = None

    def render_template(self, route_path: str) -> Tuple[str, str]:
        """
        Render a Svelte component with SSR

        Args:
            route_path: The route path to render

        Returns:
            Tuple of (html, status_code)
        """
        try:
            return self._render_via_sidecar(route_path)
        except TemplateError as e:
            print(f"{Color.FAIL}Template error: {e.message}{Color.ENDC}")
            return f"<div>Template Error: {e.message}</div>", "404 NOT FOUND"
        except CompilationError as e:
            print(f"{Color.FAIL}Compilation error: {e.message}{Color.ENDC}")
            return f"<div>Compilation Error: {e.message}</div>", "500 INTERNAL SERVER ERROR"
        except RenderingError as e:
            print(f"{Color.FAIL}Rendering error: {e.message}{Color.ENDC}")
            return f"<div>Rendering Error: {e.message}</div>", "500 INTERNAL SERVER ERROR"
        except Exception as e:
            print(f"{Color.FAIL}Unexpected error: {str(e)}{Color.ENDC}")
            return f"<div>Server Error: {str(e)}</div>", "500 INTERNAL SERVER ERROR"
    
    def _render_via_sidecar(self, route_path: str) -> Tuple[str, str]:
        """New pipeline: render via Node sidecar with prebuilt SSR module."""
        from fymo.core.sidecar import SidecarError
        from fymo.core.manifest_cache import ManifestUnavailable
        from fymo.core.html import build_html

        route_info = self.router.match(route_path)
        if not route_info:
            return self._render_404(), "404 NOT FOUND"

        controller_key = route_info["controller"]
        route_name = controller_key.split(".")[0]
        controller_module = f"app.controllers.{controller_key}"
        params = route_info.get("params", {})
        _, props, doc_meta = self._load_controller_data(controller_module, params=params)

        try:
            manifest = self.manifest_cache.get()
        except ManifestUnavailable as e:
            return f"<div>Build error: {e}</div>", "500 INTERNAL SERVER ERROR"

        if route_name not in manifest.routes:
            return (
                f"<div>Route '{route_name}' not in manifest. Run `fymo build`.</div>",
                "500 INTERNAL SERVER ERROR",
            )

        try:
            ssr = self.sidecar.render(route_name, props, doc=doc_meta)
        except SidecarError as e:
            return f"<div>SSR Error: {e}</div>", "500 INTERNAL SERVER ERROR"

        title = doc_meta.get("title", self.config_manager.get_app_name())
        head_extra = self._generate_head_content(doc_meta.get("head", {}))
        # Prepend Svelte's own <head> output
        head_extra = (ssr["head"] or "") + head_extra

        html = build_html(
            body=ssr["body"],
            head_extra=head_extra,
            props=props,
            assets=manifest.routes[route_name],
            title=title,
            doc=doc_meta,
        )
        return html, "200 OK"

    def _load_controller_data(
        self, controller_module: str, params: dict | None = None
    ) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
        """Load controller and extract context and document metadata"""
        params = params or {}
        try:
            controller = importlib.import_module(controller_module)
            props: dict = {}
            if hasattr(controller, "getContext") and callable(getattr(controller, "getContext")):
                getContext = getattr(controller, "getContext")
                sig = inspect.signature(getContext)
                accepted = {k: v for k, v in params.items() if k in sig.parameters}
                props = getContext(**accepted)
            doc_meta: dict = {}
            if hasattr(controller, "getDoc") and callable(getattr(controller, "getDoc")):
                doc_meta = controller.getDoc()
            return controller, props, doc_meta
        except (ImportError, AttributeError) as e:
            print(f"{Color.FAIL}Controller error: {e}{Color.ENDC}")
            return None, {}, {}
    
    def _generate_head_content(self, head_data: Dict[str, Any]) -> str:
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
            self._add_analytics_scripts(head_parts, script_data)
            self._add_custom_scripts(head_parts, script_data)
        
        return '\n' + '\n'.join(head_parts) + '\n' if head_parts else ""
    
    def _add_analytics_scripts(self, head_parts: list, script_data: Dict[str, Any]) -> None:
        """Add analytics scripts to head parts"""
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
    
    def _add_custom_scripts(self, head_parts: list, script_data: Dict[str, Any]) -> None:
        """Add custom scripts to head parts"""
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
    
    def _escape_html_attr(self, value: str) -> str:
        """Escape HTML attribute values"""
        return (value.replace('&', '&amp;')
                     .replace('<', '&lt;')
                     .replace('>', '&gt;')
                     .replace('"', '&quot;')
                     .replace("'", '&#x27;'))
    
    def _sanitize_js(self, js_code: str) -> str:
        """Basic JavaScript sanitization - remove dangerous patterns"""
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
