"""
Fymo Server - Core WSGI application
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from fymo.core.config import ConfigManager
from fymo.core.assets import AssetManager
from fymo.core.template_renderer import TemplateRenderer
from fymo.core.router import Router


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def _load_identity_secret(project_root: Path, dev: bool) -> bytes:
    """Resolve the HMAC secret used to sign fymo_uid cookies.

    Resolution order:
      1. FYMO_SECRET env var — used as raw utf-8 bytes; must be ≥ 16 chars.
      2. Read .fymo/secret.key if it exists (≥ 16 bytes).
      3. Dev mode only: auto-generate .fymo/secret.key (32 random bytes).
      4. Production with neither: raise. Loud failure beats forgeable cookies.
    """
    raw = os.environ.get("FYMO_SECRET", "").strip()
    if raw:
        b = raw.encode("utf-8")
        if len(b) < 16:
            raise RuntimeError(
                "FYMO_SECRET is set but is shorter than 16 characters. "
                "Use a long random string, e.g.: "
                "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return b

    secret_path = project_root / ".fymo" / "secret.key"
    if secret_path.is_file():
        data = secret_path.read_bytes()
        if len(data) >= 16:
            return data

    if not dev:
        raise RuntimeError(
            "FYMO_SECRET environment variable is required in production "
            "(set FymoApp(dev=True) or FYMO_DEV=1 for local development, "
            "in which case a per-project secret will be auto-generated at "
            f"{secret_path}). Generate one with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )

    import secrets as _secrets
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    new_secret = _secrets.token_bytes(32)
    secret_path.write_bytes(new_secret)
    try:
        secret_path.chmod(0o600)
    except Exception:
        pass
    return new_secret


class FymoApp:
    """Main Fymo application class"""

    def __init__(
        self,
        project_root: Optional[Path] = None,
        config: Optional[Dict] = None,
        dev: Optional[bool] = None,
    ):
        """
        Initialize Fymo application

        Args:
            project_root: Root directory of the project
            config: Configuration dictionary
            dev: Dev mode flag. If None, reads FYMO_DEV env var (default False).
                 When True: 500 responses include tracebacks; cookies omit Secure flag
                 even on https; verbose logging. Production must leave dev=False.
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.dev = dev if dev is not None else _env_truthy("FYMO_DEV")

        # Wire the dev flag into the remote router so its 500 path knows whether
        # to include traceback details.
        from fymo.remote import router as _remote_router
        _remote_router._dev_mode = self.dev

        # Resolve and install the HMAC secret used to sign fymo_uid cookies.
        # Done eagerly at startup so production misconfiguration fails fast
        # instead of on the first remote call.
        from fymo.remote import identity as _identity
        _identity.set_secret(_load_identity_secret(self.project_root, self.dev))

        # Ensure project_root is on sys.path so that app.* packages are importable
        # (needed for remote function dispatch and convention-based routing)
        project_root_str = str(self.project_root)
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)

        # Evict any stale app.* module cache entries so that controllers from a
        # previous project root (e.g. a different tmp dir in tests) are not
        # returned by importlib.import_module for this project's files.
        for key in list(sys.modules.keys()):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]

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

        # Dev mode: SSE reload support
        self.dev_orchestrator = None

        # Sidecar + manifest cache. Always on now; legacy path remains for any
        # caller that bypasses TemplateRenderer's sidecar branch.
        from fymo.core.sidecar import Sidecar
        from fymo.core.manifest_cache import ManifestCache
        dist_dir = self.project_root / "dist"
        if (dist_dir / "sidecar.mjs").is_file():
            self.sidecar = Sidecar(dist_dir=dist_dir)
            self.sidecar.start()
            self.sidecar.ping()
            self.manifest_cache = ManifestCache(dist_dir=dist_dir)
            from fymo.core.manifest_cache import set_shared_cache
            set_shared_cache(self.manifest_cache)
            self.template_renderer.sidecar = self.sidecar
            self.template_renderer.manifest_cache = self.manifest_cache
            # Reap the Node child on normal interpreter shutdown so we don't
            # leave orphan processes behind. Covers gunicorn worker exits,
            # Ctrl-C, and any sys.exit() path that lets atexit fire.
            self._register_shutdown()
        else:
            # Fail fast at startup with a clear message; the legacy template
            # renderer path will not work either without manifest+sidecar in
            # the new world. Tell the user what to do.
            raise RuntimeError(
                f"dist/ not found at {dist_dir}. Run `fymo build` first."
            )

    def _register_shutdown(self) -> None:
        """Best-effort cleanup on interpreter exit + SIGTERM/SIGINT.

        atexit handles normal exits (gunicorn worker shutdown, sys.exit,
        Ctrl-C → KeyboardInterrupt → exit). Signal handlers cover SIGTERM
        delivered without going through Python's exception handling
        (e.g. `kill <pid>` against a long-running gunicorn worker).
        """
        import atexit
        import signal
        import threading

        # Avoid registering twice if FymoApp is constructed multiple times in
        # the same process (rare, but happens in tests).
        if getattr(self, "_shutdown_registered", False):
            return
        self._shutdown_registered = True

        def _shutdown() -> None:
            sc = getattr(self, "sidecar", None)
            if sc is None:
                return
            try:
                sc.stop()
            except Exception:
                pass

        atexit.register(_shutdown)

        # Signal handlers must be installed from the main thread. WSGI
        # workers usually run in the main thread; if not, skip silently.
        if threading.current_thread() is not threading.main_thread():
            return
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                prior = signal.getsignal(sig)
            except (ValueError, OSError):
                continue

            def _handler(signum, frame, _prior=prior):
                _shutdown()
                # Chain to whatever was installed before us so frameworks
                # like gunicorn keep their own SIGTERM behavior.
                if callable(_prior) and _prior not in (signal.SIG_DFL, signal.SIG_IGN):
                    try:
                        _prior(signum, frame)
                        return
                    except Exception:
                        pass
                # Default behavior: re-raise the signal so the process exits
                # with the conventional 128+signum status.
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass

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
    
    
    def _dev_sse(self, start_response):
        """Server-sent events: push 'reload' on rebuild events from DevOrchestrator."""
        if self.dev_orchestrator is None:
            start_response("404 NOT FOUND", [("Content-Type", "text/plain")])
            return [b"not running in dev mode"]
        start_response("200 OK", [
            ("Content-Type", "text/event-stream"),
            ("Cache-Control", "no-cache"),
        ])
        from queue import Queue, Empty
        q: Queue = Queue()
        def listener(event):
            if event.get("type") in ("client-rebuild", "server-rebuild"):
                q.put("reload")
        self.dev_orchestrator.add_listener(listener)
        def stream():
            yield b"data: hello\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n".encode()
                except Empty:
                    yield b": keepalive\n\n"
        return stream()

    def __call__(self, environ, start_response):
        """WSGI application callable"""
        path = environ.get("PATH_INFO", "/")

        if path.startswith("/_fymo/remote/"):
            from fymo.remote import router as router_mod
            if getattr(self, "manifest_cache", None) is not None:
                router_mod._resolve_module_for_hash = self.manifest_cache.module_for_hash
            return router_mod.handle_remote(environ, start_response)

        if path.startswith("/_fymo/data/"):
            from fymo.core.soft_nav import handle_data
            return handle_data(self, environ, start_response)

        if path == "/_dev/reload":
            return self._dev_sse(start_response)

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


def create_app(
    project_root: Optional[Path] = None,
    config: Optional[Dict] = None,
    dev: Optional[bool] = None,
) -> FymoApp:
    """
    Factory function to create a Fymo application

    Args:
        project_root: Root directory of the project
        config: Configuration dictionary
        dev: Dev mode flag (defaults to FYMO_DEV env var). Production must be False.

    Returns:
        FymoApp instance
    """
    return FymoApp(project_root, config, dev=dev)
