"""Dev orchestrator: spawns Node watcher, parses its event stream, manages sidecar lifecycle."""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from fymo.build.discovery import discover_routes
from fymo.build.entry_generator import write_client_entries
from fymo.build.hygiene import check_directory_hygiene, format_hygiene_error
from fymo.build.manifest import Manifest, RemoteModuleAssets, RouteAssets
from fymo.remote.codegen import emit_module, emit_runtime
from fymo.remote.discovery import discover_remote_modules


class DevOrchestrator:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.dist_dir = self.project_root / "dist"
        self.cache_dir = self.project_root / ".fymo" / "entries"
        self.dev_script = Path(__file__).resolve().parent / "js" / "dev.mjs"
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._listeners: List[Callable[[dict], None]] = []
        self._latest_metafile: Optional[dict] = None
        self._routes = []
        self._remote_assets: dict[str, RemoteModuleAssets] = {}

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        """Register a callback invoked on every event from the watcher (e.g. SSE push)."""
        self._listeners.append(fn)

    def start(self) -> None:
        # Pure filesystem check first, same ordering rationale as
        # BuildPipeline.build() -- no external dependency, so it shouldn't
        # be masked by (or wait on) the node-availability check.
        hygiene_violations = check_directory_hygiene(self.project_root)
        if hygiene_violations:
            raise RuntimeError(format_hygiene_error(hygiene_violations))
        if shutil.which("node") is None:
            raise RuntimeError("node not found on PATH")
        templates = self.project_root / "app" / "templates"
        self._routes = discover_routes(templates)
        client_entries = write_client_entries(self._routes, self.cache_dir, self.project_root, dev=True)

        # Discover app/remote/*.py (+ auth providers') remote functions and
        # emit their dist/client/_remote/<name>.{js,d.ts} stubs, exactly like
        # BuildPipeline does — otherwise a project that runs `fymo dev`
        # without a prior `fymo build` has no $remote/* stubs to resolve,
        # and every manifest fymo dev writes omits remote_modules entirely,
        # so any SSR prop referencing a remote function (e.g. a controller
        # passing a remote callable to a template) crashes with "remote
        # module '...' has no hash in manifest" — even under `fymo serve`
        # afterward, since serve just reads whatever fymo dev last wrote.
        remote_out = self.dist_dir / "client" / "_remote"
        project_root_str = str(self.project_root)
        import sys as _sys
        _added = project_root_str not in _sys.path
        if _added:
            _sys.path.insert(0, project_root_str)
        try:
            remote_modules = discover_remote_modules(
                self.project_root, auth_config=self._read_yaml_section("auth"),
                remote_config=self._read_yaml_section("remote"),
            )
        finally:
            if _added and project_root_str in _sys.path:
                _sys.path.remove(project_root_str)
        if remote_modules:
            emit_runtime(remote_out)
            for module_name, fns in remote_modules.items():
                emit_module(module_name, fns, remote_out)

        # $broadcast client codegen — same shared entry point BuildPipeline
        # uses, so dev and prod builds can't drift.
        from fymo.broadcast.codegen import emit_broadcast_client
        emit_broadcast_client(self.project_root, self.dist_dir)

        self._remote_assets = {
            module_name: RemoteModuleAssets(hash=next(iter(fns.values())).module_hash, fns=sorted(fns.keys()))
            for module_name, fns in remote_modules.items()
            if fns
        }

        config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": [{"name": r.name, "entryPath": str(r.entry_path)} for r in self._routes],
            "clientEntries": {n: str(p) for n, p in client_entries.items()},
        }
        self._proc = subprocess.Popen(
            ["node", str(self.dev_script), json.dumps(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.project_root),
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_yaml_section(self, key: str) -> dict:
        fymo_yml = self.project_root / "fymo.yml"
        if not fymo_yml.is_file():
            return {}
        try:
            import yaml
            data = yaml.safe_load(fymo_yml.read_text()) or {}
        except Exception:
            return {}
        return data.get(key) or {}

    def stop(self) -> None:
        self._stop_evt.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop_evt.is_set():
                return
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        if event.get("type") == "client-rebuild" and not event.get("errors"):
            self._latest_metafile = event.get("metafile")
            self._write_manifest()
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:
                pass

    def _write_manifest(self) -> None:
        if self._latest_metafile is None:
            return
        outputs = self._latest_metafile.get("outputs", {})

        project_root_abs = self.project_root.resolve()
        dist_dir_abs = self.dist_dir.resolve()

        def to_rel_dist(out_path: str):
            p = Path(out_path)
            if not p.is_absolute():
                p = project_root_abs / p
            try:
                return p.resolve().relative_to(dist_dir_abs).as_posix()
            except ValueError:
                return None

        client_by_route = {}
        css_by_route = {}
        chunks = []
        for out_path, info in outputs.items():
            rel = to_rel_dist(out_path)
            if rel is None:
                continue
            entry = info.get("entryPoint")
            if entry:
                for r in self._routes:
                    if Path(entry).name == f"{r.name}.client.js":
                        if rel.endswith(".js"):
                            client_by_route[r.name] = rel
                            css_bundle = info.get("cssBundle")
                            if css_bundle:
                                css_rel = to_rel_dist(css_bundle)
                                if css_rel:
                                    css_by_route[r.name] = css_rel
            elif Path(out_path).name.startswith("chunk-") and rel.endswith(".js"):
                chunks.append(rel)

        routes = {}
        for r in self._routes:
            if r.name in client_by_route:
                routes[r.name] = RouteAssets(
                    ssr=f"ssr/{r.name}.mjs",
                    client=client_by_route[r.name],
                    css=css_by_route.get(r.name),
                    preload=chunks,
                )
        if routes:
            Manifest(
                routes=routes,
                build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                remote_modules=self._remote_assets,
            ).write(self.dist_dir / "manifest.json")
