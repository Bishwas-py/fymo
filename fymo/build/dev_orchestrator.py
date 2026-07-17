"""Dev orchestrator: spawns Node watcher, parses its event stream, manages sidecar lifecycle."""
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from fymo.build.manifest import Manifest, RemoteModuleAssets
from fymo.build.manifest_matching import match_esbuild_outputs
from fymo.build.prepare import BuildError, prepare_build_config


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
        self._remote_assets: dict[str, RemoteModuleAssets] = {}

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        """Register a callback invoked on every event from the watcher (e.g. SSE push)."""
        self._listeners.append(fn)

    def start(self) -> None:
        # prepare_build_config raises BuildError for hygiene violations and a
        # missing `node` executable; translate both to RuntimeError here so
        # callers/tests see the same exception type this method has always
        # raised for them (grep tests/build/test_dev_orchestrator.py -- they
        # assert RuntimeError, not BuildError).
        try:
            config = prepare_build_config(self.project_root, self.dist_dir, self.cache_dir, dev=True)
        except BuildError as e:
            raise RuntimeError(str(e)) from e

        self._routes = config.routes
        self._all_layouts = config.all_layouts
        self._remote_assets = config.remote_assets

        dev_config = {
            "projectRoot": str(self.project_root),
            "distDir": str(self.dist_dir),
            "routes": config.ssr_entries,
            "clientEntries": config.client_entries,
        }
        self._proc = subprocess.Popen(
            ["node", str(self.dev_script), json.dumps(dev_config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.project_root),
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

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

        route_assets, layout_assets = match_esbuild_outputs(
            client_outputs=outputs,
            routes=self._routes,
            all_layouts=self._all_layouts,
            project_root=self.project_root,
            dist_dir=self.dist_dir,
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
            ).write(self.dist_dir / "manifest.json")
