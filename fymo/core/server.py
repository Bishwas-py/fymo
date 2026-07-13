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

        # Structured logging: human-readable in dev, one JSON object per
        # line in prod. Configured once per FymoApp construction; idempotent,
        # so repeated construction (e.g. across a test session) never piles
        # up duplicate handlers or duplicate log lines.
        from fymo.core.logging import configure as _configure_logging
        _configure_logging(json=not self.dev)

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

        # Wire the remote `@remote` opt-in flag into the router, mirroring
        # _dev_mode above. Must agree with what discovery used at build time
        # (fymo/build/pipeline.py) — otherwise a function could be listed in
        # the client manifest but 404 at dispatch, or vice versa.
        remote_cfg = self.config_manager.get_remote_config()
        _remote_router._explicit_optin = bool(remote_cfg.get("explicit_optin", False))

        self.asset_manager = AssetManager(self.project_root)
        # App-level raw HTTP routes (e.g. media streaming) — optional
        # extension point, independent of auth. See fymo/core/http.py.
        from fymo.core.http import discover_app_http_routes
        self._app_routes = discover_app_http_routes(self.project_root)
        self.router = self._initialize_router()
        self.template_renderer = TemplateRenderer(
            self.project_root,
            self.config_manager,
            self.asset_manager,
            self.router,
            dev=self.dev
        )

        # Production middleware: rate limit, body cap, security headers.
        # Settings are read once from fymo.yml at startup; the limiter is
        # shared across all requests for this process.
        from fymo.core.middleware import MiddlewareSettings, RateLimiter
        self.middleware = MiddlewareSettings.from_yaml(
            limits=self.config_manager.get_limits_config(),
            security=self.config_manager.get_security_config(),
            dev=self.dev,
        )
        self.rate_limiter = RateLimiter(self.middleware.rate_limit_config)

        # Same trust_proxy flag also gates whether X-Forwarded-Proto is
        # honored when resolving the session cookie's Secure flag — a
        # module-level seam since the remote-function world (request_scope())
        # has no FymoApp reference. See fymo/remote/context.py.
        from fymo.remote import context as _remote_context
        _remote_context.set_trust_proxy(self.middleware.rate_limit_config.trust_proxy)

        # Optional auth subsystem. When enabled, a UserStore is constructed
        # and registered process-wide so current_user() / @require_auth can
        # find it from any remote function. The built-in `auth` system
        # module is also registered with discovery so signup/login/logout/me
        # appear in the manifest like any other remote function.
        self.auth_enabled = False
        auth_cfg = self.config_manager.get_auth_config()
        if auth_cfg.get("enabled"):
            self._init_auth(auth_cfg)
        # Mirror onto the renderer (constructed above, before auth_enabled was
        # known) so SSR only opens a request scope for apps that use auth --
        # see TemplateRenderer._ssr_request_scope.
        self.template_renderer.auth_enabled = self.auth_enabled

        # Job provider: always on (default ThreadedJobProvider needs no
        # config), mirroring get_shared_runner()'s always-available default.
        # Discovers app/jobs/*.py, builds the configured provider (fymo.yml's
        # `jobs:` section), and registers it process-wide so remote functions
        # can call `get_job_provider().submit(...)` without wiring anything
        # themselves.
        from fymo.jobs import init_job_provider
        self.job_provider = init_job_provider(
            self.project_root, self.config_manager.get_jobs_config().get("provider")
        )

        # Broadcasts: same always-on treatment. Discovers app/broadcasts/*.py
        # and installs the configured BroadcastProvider so publish() works
        # from any remote function and the /_fymo/broadcast SSE endpoint can
        # resolve channels.
        from fymo.broadcast import init_broadcasts
        self.broadcast_provider = init_broadcasts(
            self.project_root, self.config_manager.get_broadcasts_config().get("provider")
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

    @staticmethod
    def _load_configured_class(dotted_path: str):
        """Resolve a dotted `module.sub.ClassName` config path to the class object.

        Shared by the `auth.user_store` and `auth.email_sender` loading below —
        both take a dotted path from fymo.yml and need the same
        rpartition + import_module + getattr resolution. Raises
        ValueError/ImportError/AttributeError on a bad path; instantiation is
        left to the caller (kept out of this helper) so a constructor failure
        is never mistaken for, or reported as, an import failure.
        """
        module_path, _, cls_name = dotted_path.rpartition(".")
        if not module_path or not cls_name:
            raise ValueError(f"invalid path: {dotted_path!r}")
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)

    def _init_auth(self, auth_cfg: dict) -> None:
        """Instantiate the configured UserStore and register it process-wide."""
        store_path = auth_cfg.get("user_store") or "fymo.auth.store.SqliteUserStore"
        try:
            cls = self._load_configured_class(store_path)
        except Exception as e:
            raise RuntimeError(
                f"auth.user_store={store_path!r} could not be imported: {e}"
            ) from e

        store = cls(self.project_root)
        from fymo.auth.context import set_user_store
        set_user_store(store)
        self.user_store = store

        # Instantiate the configured EmailSender (default: logs the
        # verification link, no SMTP dependency) and register it process-wide.
        # Same dotted-path-in-fymo.yml pattern as auth.user_store above.
        sender_path = auth_cfg.get("email_sender") or "fymo.auth.email.LoggingEmailSender"
        try:
            sender_cls = self._load_configured_class(sender_path)
        except Exception as e:
            raise RuntimeError(
                f"auth.email_sender={sender_path!r} could not be imported: {e}"
            ) from e

        sender = sender_cls(self.project_root)
        from fymo.auth.context import set_email_sender
        set_email_sender(sender)
        self.email_sender = sender

        # Build the configured providers and install their session resolvers.
        # Defaults to [password]; extra providers (OAuth, token) come from
        # auth.providers in fymo.yml.
        from fymo.auth.providers.registry import (
            build_providers, install_providers, system_remote_modules,
        )
        providers = build_providers(auth_cfg.get("providers"))
        install_providers(providers)
        self.auth_providers = providers
        # Register providers' remote functions (password → `auth` module) with
        # the remote router — replaces the old hardcoded _SYSTEM_MODULES table.
        from fymo.remote import router as _remote_router
        _remote_router.set_system_modules(system_remote_modules(providers))
        # Flatten provider HTTP routes into a (method, path) -> handler map.
        self._auth_routes = {
            (r.method, r.path): r.handler
            for p in providers
            for r in p.http_routes()
        }

        self.auth_enabled = True

    def _dispatch_auth_route(self, environ, start_response, path):
        """Route /auth/... to a provider handler, or None if none matches."""
        method = environ.get("REQUEST_METHOD", "GET")
        handler = self._auth_routes.get((method, path))
        if handler is None:
            return None
        return handler(environ, start_response)

    def shutdown(self) -> None:
        """Stop this app's Node sidecar.

        Public and idempotent: safe to call more than once (e.g. once from a
        gunicorn `worker_exit` hook and again from the atexit/SIGTERM handlers
        registered by `_register_shutdown`, or from a test's own teardown).
        `Sidecar.stop()` is itself a no-op once the process is already gone,
        so repeated calls just return immediately.
        """
        sc = getattr(self, "sidecar", None)
        if sc is None:
            return
        try:
            sc.stop()
        except Exception:
            pass

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

        atexit.register(self.shutdown)

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
                self.shutdown()
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
        self.shutdown()
    
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
    
    def render_svelte_template(self, route_path: str, environ: dict | None = None) -> tuple[str, str]:
        """
        Render a Svelte component with SSR

        Args:
            route_path: The route path to render
            environ: The WSGI environ of the request, when available. Passed
                through to the controller so current_user() can resolve the
                session cookie during SSR when auth is enabled.

        Returns:
            Tuple of (html, status_code)
        """
        return self.template_renderer.render_template(route_path, environ)
    
    
    def serve_asset(self, path: str) -> tuple[str, str, str]:
        """
        Serve static assets
        
        Returns:
            Tuple of (content, status, content_type)
        """
        return self.asset_manager.serve_asset(path)
    
    
    def _healthz(self, start_response):
        """Liveness probe: 200 if the Node sidecar responds to ping, else 503.

        Bypasses auth, the SSR render path, and the body-cap/rate-limit
        middleware entirely — this must work even when auth is enabled, the
        sidecar itself is what's unhealthy, or a load balancer / k8s probe is
        polling faster than the configured rate limit. Cache-Control: no-cache
        keeps a caching proxy from serving a stale 200 after the sidecar dies.
        """
        import json as _json
        try:
            self.sidecar.ping()
            body = _json.dumps({"status": "ok"}).encode("utf-8")
            status = "200 OK"
        except Exception:
            body = _json.dumps({"status": "degraded"}).encode("utf-8")
            status = "503 SERVICE UNAVAILABLE"
        start_response(status, [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-cache"),
        ])
        return [body]

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

        # 0. Liveness probe. Dispatched before body-cap/rate-limit so a load
        # balancer or k8s probe polling faster than the configured rate limit
        # never sees a 429/413 and mistakes a healthy instance for a dead one.
        # Also bypasses access logging — health checks poll far too often to
        # be worth a log line each, and they'd otherwise drown out real
        # traffic in the log stream.
        if path == "/healthz":
            return self._healthz(start_response)

        # Everything else is timed and access-logged in `finally`, however it
        # exits (normal return or an exception raised before start_response
        # runs).
        import time
        from fymo.core.logging import access_log

        start_time = time.perf_counter()
        status_holder: Dict[str, Any] = {"status": None}

        def _capture_status(status, headers, exc_info=None):
            status_holder["status"] = status
            if exc_info is not None:
                return start_response(status, headers, exc_info)
            return start_response(status, headers)

        try:
            return self._dispatch(environ, _capture_status)
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            access_log(environ, status_holder["status"], duration_ms)

    def _dispatch(self, environ, start_response):
        """The normal (non-healthz) request path — body cap, rate limit,
        security headers, routing. Split out from `__call__` so the latter
        can wrap it uniformly with request timing + access logging."""
        path = environ.get("PATH_INFO", "/")

        # 1. Body cap. Reject oversized requests before reading wsgi.input.
        from fymo.core.middleware import (
            check_body_limit,
            respond_413,
            respond_429,
            wrap_start_response,
        )
        if not check_body_limit(environ, self.middleware.max_body_bytes):
            return respond_413(start_response, self.middleware.max_body_bytes)

        # 2. Rate limit. Token bucket keyed by (client_ip, path-rule).
        allowed, info = self.rate_limiter.check(environ)
        if not allowed:
            return respond_429(start_response, info)

        # 3. Security headers wrapper. Injects defaults into every response.
        if self.middleware.security_headers_enabled:
            start_response = wrap_start_response(
                start_response, environ, self.middleware.extra_security_headers,
                dev=self.middleware.dev,
                trust_proxy=self.middleware.rate_limit_config.trust_proxy,
            )

        # Provider-mounted auth routes (OAuth start/callback, etc.).
        if getattr(self, "auth_enabled", False) and path.startswith("/auth/"):
            handled = self._dispatch_auth_route(environ, start_response, path)
            if handled is not None:
                return handled

        if path.startswith("/_fymo/remote/"):
            from fymo.remote import router as router_mod
            if getattr(self, "manifest_cache", None) is not None:
                router_mod._resolve_module_for_hash = self.manifest_cache.module_for_hash
            return router_mod.handle_remote(environ, start_response)

        if path.startswith("/_fymo/data/"):
            from fymo.core.soft_nav import handle_data
            return handle_data(self, environ, start_response)

        if path.startswith("/_fymo/broadcast/"):
            from fymo.broadcast.sse import handle_broadcast
            return handle_broadcast(environ, start_response)

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

        # App-defined raw HTTP routes (e.g. media streaming with Range
        # support) — first match wins, in registration order.
        method = environ.get("REQUEST_METHOD", "GET")
        for route in self._app_routes:
            if method == route.method and path.startswith(route.path):
                return route.handler(environ, start_response)

        # Handle template requests
        html, status = self.render_svelte_template(path, environ)
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
