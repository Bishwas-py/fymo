"""Dev orchestrator: spawns Node watcher, parses its event stream, manages sidecar lifecycle."""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from fymo.build.composition_generator import generate_ssr_tree
from fymo.build.discovery import discover_routes, discover_all_layouts
from fymo.build.entry_generator import write_client_entries
from fymo.build.hygiene import check_directory_hygiene, format_hygiene_error
from fymo.build.manifest import Manifest, RemoteModuleAssets
from fymo.build.manifest_matching import match_esbuild_outputs
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
        self._all_layouts = []
        self._has_global_css = False
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

        # Layout + global-CSS entries, mirroring BuildPipeline.build() so
        # `fymo dev` and `fymo build` can't drift on what gets built --
        # this file previously stopped at write_client_entries() and never
        # discovered layouts or _global.css at all, which is exactly what
        # let the manifest fields below go stale (see match_esbuild_outputs
        # docstring for the bug this caused).
        self._all_layouts = discover_all_layouts(templates)
        layout_client_entries = {
            f"_layout-{ref.id}": str(ref.svelte_path) for ref in self._all_layouts
        }
        global_css_path = templates / "_global.css"
        self._has_global_css = global_css_path.is_file()
        global_css_entry = {"_global": str(global_css_path)} if self._has_global_css else {}

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

        # SSR entry points: composed tree file when a route has a layout
        # chain, else the raw leaf -- same rule as BuildPipeline.build().
        # Without this, the SSR bundle is always the bare leaf regardless of
        # layout_chain, so a route with a real layout never renders its
        # <RootLayout>/<ResourceLayout> wrapper at all under `fymo dev`.
        ssr_entries = [
            {"name": r.name, "entryPath": str(generate_ssr_tree(r, self.cache_dir) or r.entry_path)}
            for r in self._routes
        ]

        config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": ssr_entries,
            "clientEntries": {
                **{n: str(p) for n, p in client_entries.items()},
                **layout_client_entries,
                **global_css_entry,
            },
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

        route_assets, layout_assets, global_css_out = match_esbuild_outputs(
            client_outputs=outputs,
            routes=self._routes,
            all_layouts=self._all_layouts,
            project_root=self.project_root,
            dist_dir=self.dist_dir,
            has_global_css=self._has_global_css,
        )

        # Lenient by design (unlike BuildPipeline's strict BuildError): a
        # route or layout's output can be transiently absent mid-rebuild
        # while watching, and the next successful rebuild event will catch
        # it up. Only require at least one route to be ready before writing
        # anything at all, matching this method's prior behavior.
        if route_assets:
            Manifest(
                routes=route_assets,
                build_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                remote_modules=self._remote_assets,
                layouts=layout_assets,
                global_css=global_css_out,
            ).write(self.dist_dir / "manifest.json")
