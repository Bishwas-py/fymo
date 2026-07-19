"""
Template rendering for Fymo applications
"""

import importlib
import logging
from html import escape
from pathlib import Path
from typing import Dict, Any, Tuple

from fymo.core.router import Router
from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.ssr_controller import load_controller_context, load_layout_props_and_docs, merge_docs
from fymo.remote.errors import RemoteError, Redirect
from fymo.utils.colors import Color

logger = logging.getLogger("fymo")


class TemplateRenderer:
    """Handles Svelte template rendering with SSR"""

    def __init__(self, project_root: Path, config_manager: ConfigManager,
                 asset_manager: AssetManager, router: Router, dev: bool = False):
        """
        Initialize template renderer

        Args:
            project_root: Root directory of the project
            config_manager: Configuration manager instance
            asset_manager: Asset manager instance
            router: Router instance
            dev: Dev mode flag. When True, 500 error bodies include the
                 (escaped) exception text. When False (prod), error bodies
                 are generic and the real exception is only logged.
        """
        self.project_root = project_root
        self.config_manager = config_manager
        self.asset_manager = asset_manager
        self.router = router
        self.dev = dev
        self.sidecar = None
        self.manifest_cache = None

    def _render_error(
        self,
        e: Exception,
        generic_message: str,
        status: str = "500 INTERNAL SERVER ERROR",
    ) -> Tuple[str, str]:
        """
        Build a safe error body for an unexpected exception.

        Exception messages frequently echo user-controlled input (e.g. a
        route param that failed `int()` conversion appears verbatim in the
        message), so they must never be interpolated into HTML unescaped.
        This is the single place in the module that is allowed to turn an
        exception into HTML; every error branch must route through it.

        In dev mode, the escaped exception text is shown so developers can
        see what went wrong. In prod, the body is a static generic message
        with no exception text at all; the real details are logged instead.

        Args:
            e: The exception that was raised
            generic_message: Short generic label describing the failure
                (e.g. "Server Error", "SSR Error")
            status: HTTP status line to return (default 500)

        Returns:
            Tuple of (html, status_code)
        """
        # Full traceback always goes to the server log, never to the HTTP
        # client (which gets the generic message in prod) -- prod incident
        # debugging needs it regardless of dev/prod mode.
        logger.error("%s: %s", generic_message, e, exc_info=True)
        if self.dev:
            return f"<div>{generic_message}: {escape(str(e))}</div>", status
        return f"<div>{generic_message}</div>", status

    def render_template(
        self, route_path: str, environ: dict | None = None
    ) -> Tuple[str, str, list[tuple[str, str]]]:
        """
        Render a Svelte component with SSR

        Args:
            route_path: The route path to render
            environ: The WSGI environ of the request, when available. Threaded
                down to the controller so a read-only request scope can be
                opened around getContext()/getDoc(), which is what lets
                current_uid() resolve the request's identity during SSR
                instead of only after hydration. None for callers that don't
                have (or don't need) a request, e.g. direct render_template()
                calls in tests.

        Returns:
            Tuple of (html, status_code, extra_headers). extra_headers is
            normally empty; a raised Redirect populates it with a Location
            header (see _render_redirect below) so the WSGI layer can attach
            it to the response without every other caller having to know
            about headers at all.
        """
        try:
            html, status = self._render_via_sidecar(route_path, environ)
            return html, status, []
        except RemoteError as e:
            if isinstance(e, Redirect):
                return self._render_redirect(e)
            # A controller's getContext() raised NotFound/Unauthorized/etc.
            # directly (not via a remote-function RPC call) -- e.g. a page
            # controller doing `get_post(slug)` and getting a 404-shaped
            # domain error for a missing row. Without this branch every one
            # of these fell through to the generic 500 below, even though
            # RemoteError already carries the right status/code. Reuses the
            # exact status/code convention remote functions use over RPC, so
            # a controller can raise the same NotFound its own remote
            # functions already raise instead of the SSR path flattening it.
            status_line = f"{e.status} {e.code.upper().replace('_', ' ')}"
            label = e.code.replace('_', ' ').title()
            print(f"{Color.FAIL}{label}: {e}{Color.ENDC}")
            html, status = self._render_error(e, label, status=status_line)
            return html, status, []
        except Exception as e:
            print(f"{Color.FAIL}Unexpected error: {str(e)}{Color.ENDC}")
            html, status = self._render_error(e, "Server Error")
            return html, status, []

    def _render_redirect(self, e: Redirect) -> Tuple[str, str, list[tuple[str, str]]]:
        """Turn a Redirect raised from getContext() into a real 30x.

        No HTML body: browsers never render a 30x body, they just follow the
        Location header straight to the new URL. Status line follows the
        same `code.upper()` convention every other RemoteError subclass uses
        here (see the NotFound/Unauthorized/etc branch above) rather than a
        separate HTTP-reason-phrase table.
        """
        status_line = f"{e.status} {e.code.upper()}"
        return "", status_line, [("Location", e.location)]
    
    def is_route_miss(self, route_path: str) -> bool:
        """True when no SSR route can serve this path.

        A miss is either no router match at all, or a match produced only by
        the convention-based fallback with nothing built for it in the
        manifest -- convention routing guesses a controller from any one- or
        two-segment path, so its guess only counts when the build actually
        produced that route. An explicitly declared route is never a miss:
        its absence from the manifest is a stale build, and _render_via_sidecar
        keeps reporting that as the 500 it is. Manifest read failures are also
        not a miss; they surface through the render path as Build Error.
        """
        route_info = self.router.match(route_path)
        if not route_info:
            return True
        if not route_info.get("convention"):
            return False
        if self.manifest_cache is None:
            return False
        route_name = route_info["controller"].split(".")[0]
        try:
            manifest = self.manifest_cache.get()
        except Exception:
            return False
        return route_name not in manifest.routes

    def _render_via_sidecar(self, route_path: str, environ: dict | None = None) -> Tuple[str, str]:
        """New pipeline: render via Node sidecar with prebuilt SSR module."""
        from fymo.core.sidecar import SidecarError
        from fymo.core.manifest_cache import ManifestUnavailable
        from fymo.core.html import build_html

        if self.is_route_miss(route_path):
            return self.render_404(route_path), "404 NOT FOUND"
        route_info = self.router.match(route_path)

        # Route-level require_auth (issue #80): checked before any manifest,
        # controller, or sidecar work so a protected page never renders (or
        # costs a render) for a request that will be redirected anyway.
        require_auth = route_info.get("require_auth")
        if require_auth:
            from fymo.core.page_auth import page_auth_redirect
            location = page_auth_redirect(
                require_auth, environ, self.router.signin_path(), route_path
            )
            if location is not None:
                raise Redirect(location, status=302)

        controller_key = route_info["controller"]
        route_name = controller_key.split(".")[0]
        controller_module = f"app.controllers.{controller_key}"
        params = route_info.get("params", {})

        try:
            manifest = self.manifest_cache.get()
        except ManifestUnavailable as e:
            return self._render_error(e, "Build Error")

        if route_name not in manifest.routes:
            return self._render_error(
                RuntimeError(f"Route '{route_name}' not in manifest. Run `fymo build`."),
                "Server Error",
            )
        assets = manifest.routes[route_name]

        _, leaf_props, leaf_doc = self._load_controller_data(
            controller_module, params=params, environ=environ
        )

        if assets.layout_chain:
            layout_props_by_level, layout_docs = load_layout_props_and_docs(
                assets.layout_chain, params, environ
            )
            doc_meta = merge_docs(layout_docs + [leaf_doc])
            sidecar_props = {
                "leafProps": leaf_props,
                "layoutProps": layout_props_by_level,
            }
        else:
            doc_meta = leaf_doc
            sidecar_props = leaf_props

        # The identity slot (issue #80): the public_identity projection
        # output for this request, or None when anonymous / no @identify
        # chain. Passed to the sidecar so $auth reads it during SSR,
        # then embedded in the HTML for the client store to hydrate from.
        from fymo.auth.public import client_identity
        identity = client_identity(environ)

        try:
            from fymo.core.html import _safe_json
            import json
            # Serialize props through _safe_json first so remote callables become
            # their marker dicts before being JSON-encoded for the IPC message.
            serialized_props = json.loads(_safe_json(sidecar_props))
            render_kwargs = {"doc": doc_meta}
            if identity is not None:
                render_kwargs["identity"] = identity
            ssr = self.sidecar.render(route_name, serialized_props, **render_kwargs)
        except SidecarError as e:
            return self._render_error(e, "SSR Error")

        title = doc_meta.get("title", self.config_manager.get_app_name())
        head_extra = self._generate_head_content(doc_meta.get("head", {}))
        # Prepend Svelte's own <head> output
        head_extra = (ssr["head"] or "") + head_extra

        # Union of the layout chain's CSS in chain order (root first, then
        # resource) -- each layout imports only what it adds, nesting
        # inherits the rest.
        layout_css = []
        for ref in assets.layout_chain:
            layout_asset = manifest.layouts.get(ref.id)
            if layout_asset is not None and layout_asset.css:
                layout_css.append(layout_asset.css)

        html = build_html(
            body=ssr["body"],
            head_extra=head_extra,
            props=sidecar_props,
            assets=assets,
            title=title,
            doc=doc_meta,
            disabled_soft_nav=self.router.disabled_soft_nav_resources(),
            layout_css=layout_css,
            params=params,
            identity=identity,
        )
        return html, "200 OK"

    def _load_controller_data(
        self, controller_module: str, params: dict | None = None, environ: dict | None = None
    ) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
        """Load controller and extract context and document metadata"""
        try:
            controller = importlib.import_module(controller_module)
            props, doc_meta = load_controller_context(controller, params, environ)
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

        # Generate link tags (stylesheets, canonical URLs, fonts, etc.)
        link_data = head_data.get('link', [])
        if link_data and isinstance(link_data, list):
            for link in link_data:
                if isinstance(link, dict):
                    link_attrs = []
                    for key, value in link.items():
                        safe_key = self._escape_html_attr(str(key))
                        safe_value = self._escape_html_attr(str(value))
                        link_attrs.append(f'{safe_key}="{safe_value}"')
                    if link_attrs:
                        head_parts.append(f'    <link {" ".join(link_attrs)}>')

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
    
    def render_404(self, route_path: str = "") -> str:
        """Built-in 404 page for a route miss.

        Dev mode gets the routing hint; prod gets a clean minimal page with
        zero internals. The echoed path is user-controlled and must be
        escaped. App-customizable error pages are a separate future feature.
        """
        if self.dev:
            detail = (
                f"<p>No route matched <code>{escape(route_path)}</code>. "
                "Routes are declared in fymo.yml's <code>routes:</code> "
                "section or in <code>config/routes.py</code>.</p>"
            )
        else:
            detail = "<p>The requested page could not be found.</p>"
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>404 - Not Found</title>
</head>
<body>
    <h1>404 - Page Not Found</h1>
    {detail}
</body>
</html>"""
